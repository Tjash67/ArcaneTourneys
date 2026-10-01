import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
from datetime import datetime, timedelta
from typing import Optional
import asyncio
import aiohttp
import base64

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

# ==================== CONFIGURATION ====================
# Credentials are loaded from the environment. Never commit real values.
DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN', '')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')

# GitHub Auto-Sync Configuration (FREE!)
# 1. Create a GitHub repo for your website files
# 2. Go to GitHub → Settings → Developer Settings → Personal Access Tokens → Tokens (classic)
# 3. Generate new token with 'repo' scope
# 4. Connect your repo to Netlify for auto-deploy
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN', '')
GITHUB_REPO = os.getenv('GITHUB_REPO', '')
GITHUB_BRANCH = os.getenv('GITHUB_BRANCH', 'main')
ENABLE_AUTO_SYNC = os.getenv('ENABLE_AUTO_SYNC', 'false').lower() == 'true'

# Gemini API endpoint
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

# Data storage
TOURNAMENT_DATA_FILE = 'tournament_data.json'
WEBSITE_DATA_FILE = 'website_data.json'  # Formatted for website consumption

def load_data():
    if os.path.exists(TOURNAMENT_DATA_FILE):
        with open(TOURNAMENT_DATA_FILE, 'r') as f:
            return json.load(f)
    return {
        'tournaments': {},
        'teams': {},
        'matches': {},
        'server_config': {},
        'payments': {},
        'leaderboards': {
            'highest_kill_match': [],
            'total_kills': {}
        },
        'recent_matches': []
    }

def save_data(data):
    with open(TOURNAMENT_DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def generate_website_data(data):
    """Generate a clean data structure optimized for the website"""
    website_data = {
        'last_updated': datetime.now().isoformat(),
        'tournaments': [],
        'leaderboard': [],
        'recent_matches': [],
        'stats': {
            'total_tournaments': 0,
            'total_teams': 0,
            'total_prize_money': 0,
            'total_matches': 0
        }
    }
    
    # Process tournaments
    for tid, tourney in data.get('tournaments', {}).items():
        # Get teams for this tournament
        tournament_teams = []
        for team_id in tourney.get('teams', []):
            team = data.get('teams', {}).get(team_id, {})
            if team:
                total_kills = sum(m.get('kills', 0) for m in team.get('matches_played', []))
                tournament_teams.append({
                    'id': team_id,
                    'name': team.get('name', 'Unknown'),
                    'points': team.get('total_points', 0),
                    'kills': total_kills,
                    'matches_played': len(team.get('matches_played', [])),
                    'match_point': team.get('match_point_eligible', False),
                    'players': team.get('players', []),
                    'streams': team.get('streams', {}),
                    'payment_status': team.get('payment_status', 'pending')
                })
        
        # Sort teams by points
        tournament_teams.sort(key=lambda x: x['points'], reverse=True)
        
        # Parse date
        scheduled = None
        if tourney.get('scheduled_date'):
            try:
                dt = datetime.fromisoformat(tourney['scheduled_date'])
                scheduled = {
                    'iso': tourney['scheduled_date'],
                    'formatted': dt.strftime('%B %d, %Y'),
                    'time': dt.strftime('%I:%M %p'),
                    'timezone': tourney.get('timezone', 'EST')
                }
            except:
                pass
        
        website_data['tournaments'].append({
            'id': tid,
            'name': tourney.get('name', 'Unknown Tournament'),
            'status': tourney.get('status', 'unknown'),
            'date': scheduled,
            'entry_fee': tourney.get('entry_fee', 15),
            'prize_pool': tourney.get('prize_pool', 0),
            'max_teams': tourney.get('max_teams', 21),
            'registered_teams': len(tourney.get('teams', [])),
            'paid_teams': len(tourney.get('paid_teams', [])),
            'match_point_threshold': tourney.get('match_point_threshold', 135),
            'teams': tournament_teams,
            'results': tourney.get('results', None)
        })
        
        # Update stats
        website_data['stats']['total_tournaments'] += 1
        website_data['stats']['total_prize_money'] += tourney.get('prize_pool', 0)
    
    # Build global leaderboard (all-time)
    all_teams = []
    for team_id, team in data.get('teams', {}).items():
        total_kills = sum(m.get('kills', 0) for m in team.get('matches_played', []))
        all_teams.append({
            'id': team_id,
            'name': team.get('name', 'Unknown'),
            'points': team.get('total_points', 0),
            'kills': total_kills,
            'matches': len(team.get('matches_played', [])),
            'tournament': data.get('tournaments', {}).get(team.get('tournament_id', ''), {}).get('name', 'Unknown')
        })
        website_data['stats']['total_teams'] += 1
        website_data['stats']['total_matches'] += len(team.get('matches_played', []))
    
    all_teams.sort(key=lambda x: x['points'], reverse=True)
    website_data['leaderboard'] = all_teams[:50]  # Top 50
    
    # Recent matches
    website_data['recent_matches'] = data.get('recent_matches', [])[:20]
    
    return website_data

async def sync_to_github(data):
    """Push tournament data to GitHub repo (triggers Netlify auto-deploy)"""
    if not ENABLE_AUTO_SYNC:
        return False, "Auto-sync disabled"
    
    if GITHUB_TOKEN == 'YOUR_GITHUB_TOKEN_HERE':
        return False, "GitHub token not configured"
    
    if GITHUB_REPO == 'YOUR_USERNAME/YOUR_REPO_NAME':
        return False, "GitHub repo not configured"
    
    try:
        # Generate the JSON content
        file_content = json.dumps(data, indent=2)
        content_bytes = file_content.encode('utf-8')
        content_base64 = base64.b64encode(content_bytes).decode('utf-8')
        
        headers = {
            'Authorization': f'token {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json',
            'Content-Type': 'application/json'
        }
        
        file_path = 'tournament_data.json'
        api_url = f'https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}'
        
        async with aiohttp.ClientSession() as session:
            # First, try to get the current file to get its SHA (needed for updates)
            sha = None
            async with session.get(api_url, headers=headers) as response:
                if response.status == 200:
                    file_info = await response.json()
                    sha = file_info.get('sha')
            
            # Prepare the commit data
            commit_data = {
                'message': f'Auto-update tournament data - {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
                'content': content_base64,
                'branch': GITHUB_BRANCH
            }
            
            # Include SHA if updating existing file
            if sha:
                commit_data['sha'] = sha
            
            # Push to GitHub
            async with session.put(api_url, headers=headers, json=commit_data) as response:
                if response.status in [200, 201]:
                    print(f"✅ Synced to GitHub at {datetime.now().strftime('%H:%M:%S')}")
                    return True, "Synced successfully"
                else:
                    error_text = await response.text()
                    print(f"❌ GitHub sync failed: {error_text}")
                    return False, f"GitHub API error: {response.status}"
        
    except Exception as e:
        print(f"❌ GitHub sync error: {e}")
        return False, str(e)

async def save_and_sync(data):
    """Save data locally and sync to GitHub"""
    save_data(data)
    
    # Sync to GitHub in background (don't block Discord commands)
    asyncio.create_task(sync_to_github(data))

data = load_data()

# Placement multipliers (EWC/WSOW format)
PLACEMENT_MULTIPLIERS = {
    1: 15, 2: 12, 3: 10, 4: 8, 5: 7, 6: 6,
    7: 5, 8: 4, 9: 3, 10: 2, 11: 1, 12: 1
}

MATCH_POINT_THRESHOLD = 135
ENTRY_FEE = 15  # $15 per team

# ==================== COLORS ====================
COLORS = {
    'success': discord.Color.green(),
    'error': discord.Color.red(),
    'warning': discord.Color.orange(),
    'info': discord.Color.blue(),
    'gold': discord.Color.gold(),
    'military': discord.Color.from_rgb(74, 93, 35),  # Military green
    'tournament': discord.Color.from_rgb(255, 140, 0),  # Tactical orange
    'ai': discord.Color.from_rgb(138, 43, 226)  # Purple for AI responses
}

# ==================== GEMINI AI INTEGRATION ====================
async def call_gemini(prompt: str, max_tokens: int = 500) -> str:
    """Call Gemini API and return response text"""
    if GEMINI_API_KEY == 'YOUR_GEMINI_API_KEY_HERE':
        return None  # API key not configured
    
    headers = {
        "Content-Type": "application/json"
    }
    
    payload = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }],
        "generationConfig": {
            "temperature": 0.8,
            "maxOutputTokens": max_tokens,
            "topP": 0.95
        }
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{GEMINI_API_URL}?key={GEMINI_API_KEY}",
                headers=headers,
                json=payload
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    return result['candidates'][0]['content']['parts'][0]['text']
                else:
                    error_text = await response.text()
                    print(f"Gemini API error {response.status}: {error_text}")
                    return None
    except Exception as e:
        print(f"Error calling Gemini: {e}")
        return None

async def generate_welcome_message(member_name: str) -> str:
    """Generate a personalized welcome message using Gemini"""
    prompt = f"""You're Captain Price. A new recruit named "{member_name}" just walked in.

Give them ONE sentence. Maybe two if you have something clever about their name. That's it.

No fluff. No emojis. Military grit. Dark humor fine.

Examples:
- "{member_name}. Tournaments are Fridays. Don't be late."
- "Another body for the grinder. Welcome, {member_name}."
- "{member_name}, huh? We'll see if the name holds up."

Just the welcome. Nothing else."""

    response = await call_gemini(prompt, max_tokens=80)
    return response

async def answer_tournament_question(question: str, guild_id: str) -> str:
    """Use Gemini to answer tournament-related questions"""
    
    # Build context from current tournament data
    guild_config = data['server_config'].get(guild_id, {})
    tournaments_info = []
    
    for tid, tourney in data['tournaments'].items():
        if str(tourney.get('guild_id')) == guild_id:
            paid_count = len(tourney.get('paid_teams', []))
            team_count = len(tourney.get('teams', []))
            
            # Parse scheduled date
            scheduled = "TBD"
            if tourney.get('scheduled_date'):
                try:
                    dt = datetime.fromisoformat(tourney['scheduled_date'])
                    scheduled = dt.strftime('%A, %B %d, %Y at %I:%M %p') + f" {tourney.get('timezone', 'EST')}"
                except:
                    scheduled = tourney.get('scheduled_date')
            
            tournaments_info.append({
                'id': tid,
                'name': tourney['name'],
                'status': tourney['status'],
                'date': scheduled,
                'max_teams': tourney['max_teams'],
                'registered_teams': team_count,
                'paid_teams': paid_count,
                'entry_fee': tourney['entry_fee'],
                'prize_pool': tourney.get('prize_pool', 0),
                'match_point': tourney['match_point_threshold']
            })
    
    # Build teams info
    teams_info = []
    for tid, team in data['teams'].items():
        if data['tournaments'].get(team['tournament_id'], {}).get('guild_id') == int(guild_id):
            teams_info.append({
                'id': tid,
                'name': team['name'],
                'points': team['total_points'],
                'matches_played': len(team['matches_played']),
                'match_point_eligible': team['match_point_eligible'],
                'payment_status': team['payment_status']
            })
    
    # Sort teams by points
    teams_info.sort(key=lambda x: x['points'], reverse=True)
    
    context = f"""You are a grizzled Call of Duty operator running Arcane Tourneys - a competitive Warzone Resurgence Trios tournament server. Think Captain Price, Ghost, or Soap. Tactical. Direct. No-nonsense.

YOUR PERSONALITY:
- Short, direct answers. No fluff or filler.
- Military/tactical tone but not over the top
- Dry humor, dark wit when appropriate  
- You've run a hundred tournaments. You know the drill.
- Don't say "awesome" or "epic" or any corny gamer speak
- No excessive enthusiasm. Professional killer vibes.
- Answer like a soldier briefing an operator, not a customer service rep

TOURNAMENT INTEL:
- Entry: ${ENTRY_FEE} per squad (3 operators)
- Format: EWC Match Point - {MATCH_POINT_THRESHOLD} points to go live, then win a match to take it all
- Scoring: 1 point per kill + placement bonus (1st=+15, 2nd=+12, 3rd=+10, 4th=+8, 5th=+7, 6th=+6, 7th=+5, 8th=+4, 9th=+3, 10th=+2, 11th-12th=+1)
- Payout: 70% to first, 20% to second, 10% to third

REGISTRATION PROCESS:
1. /register_team - squad name + 3 Activision IDs
2. Send payment (CashApp/Venmo/PayPal) with team ID in the note
3. Admin confirms, you get tournament access
4. Show up and don't choke

ACTIVE TOURNAMENTS:
{json.dumps(tournaments_info, indent=2) if tournaments_info else "Nothing scheduled. Stand by."}

CURRENT STANDINGS:
{json.dumps(teams_info[:10], indent=2) if teams_info else "No teams in the field yet."}

COMMANDS:
/register_team - Sign up your trio
/submit_match - Log your kills and placement  
/standings - See who's on top
/team_stats - Check your squad's numbers
/help - Full command list

QUESTION: {question}

Answer direct. Keep it under 150 words. If you don't have the intel, say so."""

    response = await call_gemini(context, max_tokens=400)
    return response

# ==================== WELCOME MESSAGE ====================
@bot.event
async def on_member_join(member):
    """Welcome new members with AI-generated personalized message"""
    guild = member.guild
    
    # Find channels
    welcome_channel = discord.utils.get(guild.text_channels, name="👋-welcome")
    rules_channel = discord.utils.get(guild.text_channels, name="📜-rules")
    roles_channel = discord.utils.get(guild.text_channels, name="🎭-pick-roles")
    
    if welcome_channel:
        # Try to generate AI welcome message
        ai_welcome = await generate_welcome_message(member.display_name)
        
        if ai_welcome:
            # AI-powered welcome
            embed = discord.Embed(
                title=f"⚔️ INCOMING",
                description=ai_welcome,
                color=COLORS['military']
            )
        else:
            # Fallback to standard welcome
            embed = discord.Embed(
                title=f"⚔️ NEW CONTACT",
                description=(
                    f"**{member.display_name}.**\n\n"
                    f"You found us. Arcane Tourneys. Warzone Trios. Cash prizes.\n"
                    f"Read the rules. Find a squad. Don't waste our time."
                ),
                color=COLORS['military']
            )
        
        # Add standard info fields
        embed.add_field(
            name="📋 The Basics",
            value=f"${ENTRY_FEE} per squad | Winner takes 70% | EWC Match Point format",
            inline=False
        )
        
        if rules_channel:
            embed.add_field(name="1️⃣ Intel", value=f"Read {rules_channel.mention}. No excuses.", inline=False)
        if roles_channel:
            embed.add_field(name="2️⃣ Identify", value=f"Grab your role in {roles_channel.mention}", inline=False)
        embed.add_field(name="3️⃣ Deploy", value="Check #📢-announcements for active ops", inline=False)
        embed.add_field(name="4️⃣ Comms", value="Questions? `/ask` - I'll brief you.", inline=False)
        
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="Check your corners. Trust your squad. Win the money.")
        
        await welcome_channel.send(f"{member.mention}", embed=embed)

# ==================== AI Q&A COMMAND ====================
@bot.tree.command(name="ask", description="Ask the AI assistant about tournaments, rules, or anything!")
@app_commands.describe(question="Your question about tournaments, rules, standings, etc.")
async def ask_ai(interaction: discord.Interaction, question: str):
    """AI-powered Q&A assistant"""
    await interaction.response.defer(thinking=True)
    
    # Check if Gemini is configured
    if GEMINI_API_KEY == 'YOUR_GEMINI_API_KEY_HERE':
        embed = discord.Embed(
            title="⚠️ AI Not Configured",
            description="The AI assistant hasn't been set up yet. Please ask an admin to configure the Gemini API key.",
            color=COLORS['warning']
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    # Get AI response
    response = await answer_tournament_question(question, str(interaction.guild.id))
    
    if response:
        embed = discord.Embed(
            title="📡 COMMS",
            color=COLORS['ai']
        )
        embed.add_field(name="❓ Query", value=question, inline=False)
        embed.add_field(name="📋 Intel", value=response[:1024], inline=False)  # Discord field limit
        
        # If response is too long, add continuation
        if len(response) > 1024:
            embed.add_field(name="​", value=response[1024:2048], inline=False)
        
        embed.set_footer(text="Anything else? /help for commands.")
        await interaction.followup.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ AI Error",
            description="Sorry, I couldn't process your question. Please try again or use `/help` for the command list.",
            color=COLORS['error']
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

# ==================== AI CHAT IN CHANNEL ====================
@bot.event
async def on_message(message):
    """Respond to messages that mention the bot or start with specific triggers"""
    # Ignore bot's own messages
    if message.author == bot.user:
        return
    
    # Check if bot is mentioned or message starts with "hey bot" / "arcane"
    bot_mentioned = bot.user in message.mentions
    trigger_words = ['hey bot', 'hey arcane', 'arcane bot', '@arcane']
    has_trigger = any(message.content.lower().startswith(t) for t in trigger_words)
    
    if bot_mentioned or has_trigger:
        # Extract the question (remove mention/trigger)
        question = message.content
        for mention in message.mentions:
            question = question.replace(f'<@{mention.id}>', '').replace(f'<@!{mention.id}>', '')
        for trigger in trigger_words:
            if question.lower().startswith(trigger):
                question = question[len(trigger):]
        question = question.strip()
        
        if not question:
            await message.reply("You pinged me with nothing to say. Spit it out - tournaments, standings, registration. What do you need?")
            return
        
        # Check if Gemini is configured
        if GEMINI_API_KEY == 'YOUR_GEMINI_API_KEY_HERE':
            await message.reply("Comms are down. AI not configured. Use `/help` for now.")
            return
        
        # Show typing indicator
        async with message.channel.typing():
            response = await answer_tournament_question(question, str(message.guild.id))
        
        if response:
            embed = discord.Embed(
                description=response,
                color=COLORS['ai']
            )
            embed.set_footer(text="More questions? /ask or tag me.")
            await message.reply(embed=embed)
        else:
            await message.reply("Signal's bad. Couldn't process that. Try `/help` or `/ask`.")
    
    # Process commands
    await bot.process_commands(message)

# ==================== ROLE SELECTION ====================
class RoleSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="🎮 Player", style=discord.ButtonStyle.green, custom_id="role_player")
    async def player_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = discord.utils.get(interaction.guild.roles, name="Player")
        if role:
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role)
                await interaction.response.send_message("✅ Removed **Player** role.", ephemeral=True)
            else:
                await interaction.user.add_roles(role)
                await interaction.response.send_message("✅ Added **Player** role! You can now register for tournaments.", ephemeral=True)
    
    @discord.ui.button(label="👀 Spectator", style=discord.ButtonStyle.blurple, custom_id="role_spectator")
    async def spectator_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = discord.utils.get(interaction.guild.roles, name="Spectator")
        if role:
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role)
                await interaction.response.send_message("✅ Removed **Spectator** role.", ephemeral=True)
            else:
                await interaction.user.add_roles(role)
                await interaction.response.send_message("✅ Added **Spectator** role! You'll be notified of tournaments.", ephemeral=True)
    
    @discord.ui.button(label="🔔 Tournament Pings", style=discord.ButtonStyle.grey, custom_id="role_pings")
    async def pings_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = discord.utils.get(interaction.guild.roles, name="Tournament Pings")
        if role:
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role)
                await interaction.response.send_message("✅ Removed **Tournament Pings** role.", ephemeral=True)
            else:
                await interaction.user.add_roles(role)
                await interaction.response.send_message("✅ Added **Tournament Pings** role! You'll be pinged for announcements.", ephemeral=True)

@bot.tree.command(name="setup_roles", description="Create the role selection message")
@app_commands.default_permissions(administrator=True)
async def setup_roles(interaction: discord.Interaction):
    """Create role selection embed with buttons"""
    embed = discord.Embed(
        title="🎭 SELECT YOUR ROLES",
        description=(
            "Click the buttons below to assign yourself roles.\n"
            "Click again to remove a role.\n\n"
            "**Available Roles:**"
        ),
        color=COLORS['military']
    )
    embed.add_field(name="🎮 Player", value="You want to compete in tournaments", inline=False)
    embed.add_field(name="👀 Spectator", value="You want to watch and follow tournaments", inline=False)
    embed.add_field(name="🔔 Tournament Pings", value="Get notified about new tournaments", inline=False)
    
    await interaction.response.send_message(embed=embed, view=RoleSelectView())

# ==================== SERVER SETUP ====================
@bot.tree.command(name="setup_server", description="Set up the entire Discord server for tournaments")
@app_commands.describe(tournament_name="Name of your tournament series")
@app_commands.default_permissions(administrator=True)
async def setup_server(interaction: discord.Interaction, tournament_name: str):
    """Sets up all channels, categories, and roles for tournament"""
    await interaction.response.defer()
    
    guild = interaction.guild
    
    # Create roles
    roles_created = []
    
    # Check if roles exist, create if not
    admin_role = discord.utils.get(guild.roles, name="Tournament Admin")
    if not admin_role:
        admin_role = await guild.create_role(name="Tournament Admin", color=discord.Color.red(), hoist=True)
        roles_created.append(admin_role)
    
    mod_role = discord.utils.get(guild.roles, name="Tournament Mod")
    if not mod_role:
        mod_role = await guild.create_role(name="Tournament Mod", color=discord.Color.orange(), hoist=True)
        roles_created.append(mod_role)
    
    player_role = discord.utils.get(guild.roles, name="Player")
    if not player_role:
        player_role = await guild.create_role(name="Player", color=COLORS['military'])
        roles_created.append(player_role)
    
    spectator_role = discord.utils.get(guild.roles, name="Spectator")
    if not spectator_role:
        spectator_role = await guild.create_role(name="Spectator", color=discord.Color.light_grey())
        roles_created.append(spectator_role)
    
    pings_role = discord.utils.get(guild.roles, name="Tournament Pings")
    if not pings_role:
        pings_role = await guild.create_role(name="Tournament Pings", color=discord.Color.dark_grey())
        roles_created.append(pings_role)
    
    winner_role = discord.utils.get(guild.roles, name="🏆 Champion")
    if not winner_role:
        winner_role = await guild.create_role(name="🏆 Champion", color=discord.Color.gold(), hoist=True)
        roles_created.append(winner_role)
    
    # Create categories and channels
    # WELCOME CATEGORY
    welcome_cat = await guild.create_category("👋 WELCOME")
    await guild.create_text_channel("👋-welcome", category=welcome_cat)
    await guild.create_text_channel("📜-rules", category=welcome_cat)
    await guild.create_text_channel("🎭-pick-roles", category=welcome_cat)
    await guild.create_text_channel("🤖-ask-ai", category=welcome_cat)  # NEW: AI channel
    
    # INFO CATEGORY
    info_category = await guild.create_category("📋 TOURNAMENT INFO")
    await guild.create_text_channel("📢-announcements", category=info_category)
    await guild.create_text_channel("🏆-standings", category=info_category)
    await guild.create_text_channel("📊-schedule", category=info_category)
    await guild.create_text_channel("💰-prize-pool", category=info_category)
    
    # REGISTRATION CATEGORY
    reg_category = await guild.create_category("✍️ REGISTRATION")
    await guild.create_text_channel("🎫-register-here", category=reg_category)
    await guild.create_text_channel("💳-payment-status", category=reg_category)
    await guild.create_text_channel("✅-confirmed-teams", category=reg_category)
    
    # TOURNAMENT CATEGORY
    tourney_category = await guild.create_category("🎮 TOURNAMENT")
    await guild.create_text_channel("💬-tournament-chat", category=tourney_category)
    await guild.create_text_channel("📸-submit-results", category=tourney_category)
    await guild.create_text_channel("🔴-live-updates", category=tourney_category)
    await guild.create_text_channel("⚠️-disputes", category=tourney_category)
    
    # ADMIN CATEGORY (hidden from regular users)
    admin_category = await guild.create_category("🔧 ADMIN")
    await admin_category.set_permissions(guild.default_role, read_messages=False)
    await admin_category.set_permissions(admin_role, read_messages=True)
    await admin_category.set_permissions(mod_role, read_messages=True)
    await guild.create_text_channel("⚙️-admin-commands", category=admin_category)
    await guild.create_text_channel("💵-payment-verification", category=admin_category)
    await guild.create_text_channel("📝-match-reporting", category=admin_category)
    
    # Save server config
    data['server_config'][str(guild.id)] = {
        'tournament_name': tournament_name,
        'setup_date': datetime.now().isoformat(),
        'admin_role_id': admin_role.id,
        'mod_role_id': mod_role.id,
        'player_role_id': player_role.id,
        'spectator_role_id': spectator_role.id,
        'pings_role_id': pings_role.id,
        'winner_role_id': winner_role.id,
        'entry_fee': ENTRY_FEE
    }
    await save_and_sync(data)
    
    embed = discord.Embed(
        title="✅ SERVER SETUP COMPLETE!",
        description=f"**{tournament_name}** is ready to host tournaments!",
        color=COLORS['success']
    )
    embed.add_field(
        name="📁 Categories Created",
        value="• 👋 Welcome (with 🤖-ask-ai channel!)\n• 📋 Tournament Info\n• ✍️ Registration\n• 🎮 Tournament\n• 🔧 Admin (hidden)",
        inline=False
    )
    embed.add_field(
        name="🎭 Roles Created",
        value="• Tournament Admin\n• Tournament Mod\n• Player\n• Spectator\n• Tournament Pings\n• 🏆 Champion",
        inline=False
    )
    embed.add_field(
        name="🤖 AI Features",
        value="• AI-powered welcome messages\n• `/ask` command for Q&A\n• @mention bot for questions",
        inline=False
    )
    embed.add_field(
        name="📋 Next Steps",
        value=(
            "1. Run `/setup_roles` in #🎭-pick-roles\n"
            "2. Post rules in #📜-rules\n"
            "3. Create tournament with `/create_tournament`"
        ),
        inline=False
    )
    
    await interaction.followup.send(embed=embed)

# ==================== TOURNAMENT CREATION ====================
@bot.tree.command(name="create_tournament", description="Create a new Warzone tournament with date/time")
@app_commands.describe(
    name="Tournament name",
    date="Date of tournament (MM/DD/YYYY)",
    time="Start time (HH:MM AM/PM, e.g., 7:00 PM)",
    timezone="Timezone (EST, CST, PST, etc.)",
    max_teams="Maximum number of teams (default: 21)",
    match_point="Points needed for match point (default: 135)",
    entry_fee="Entry fee per team in dollars (default: 15)"
)
@app_commands.default_permissions(administrator=True)
async def create_tournament(
    interaction: discord.Interaction, 
    name: str,
    date: str,
    time: str,
    timezone: str = "EST",
    max_teams: Optional[int] = 21,
    match_point: Optional[int] = 135,
    entry_fee: Optional[int] = 15
):
    """Create a new tournament with scheduled date/time"""
    await interaction.response.defer()
    
    guild = interaction.guild
    
    # Parse date and time
    try:
        datetime_str = f"{date} {time}"
        # Try different formats
        for fmt in ["%m/%d/%Y %I:%M %p", "%m/%d/%Y %I:%M%p", "%m-%d-%Y %I:%M %p"]:
            try:
                tournament_datetime = datetime.strptime(datetime_str, fmt)
                break
            except ValueError:
                continue
        else:
            await interaction.followup.send("❌ Invalid date/time format! Use: MM/DD/YYYY HH:MM AM/PM", ephemeral=True)
            return
    except Exception as e:
        await interaction.followup.send(f"❌ Error parsing date/time: {e}", ephemeral=True)
        return
    
    tournament_id = f"tourney_{len(data['tournaments']) + 1}"
    
    # Create tournament-specific role
    tourney_role = await guild.create_role(
        name=f"🎮 {name}",
        color=COLORS['tournament'],
        mentionable=True
    )
    
    # Create tournament-specific category and channels
    tourney_category = await guild.create_category(f"🏆 {name.upper()}")
    
    # Set permissions - only registered players can see
    await tourney_category.set_permissions(guild.default_role, read_messages=False)
    await tourney_category.set_permissions(tourney_role, read_messages=True, send_messages=True)
    
    admin_role = guild.get_role(data['server_config'].get(str(guild.id), {}).get('admin_role_id'))
    if admin_role:
        await tourney_category.set_permissions(admin_role, read_messages=True, send_messages=True, manage_channels=True)
    
    # Create channels
    chat_channel = await guild.create_text_channel(f"💬-{name.lower().replace(' ', '-')}-chat", category=tourney_category)
    submit_channel = await guild.create_text_channel(f"📸-submit-results", category=tourney_category)
    updates_channel = await guild.create_text_channel(f"🔴-live-updates", category=tourney_category)
    
    # Create voice channels for teams
    voice_category = await guild.create_category(f"🎤 {name.upper()} VOICE")
    await voice_category.set_permissions(guild.default_role, read_messages=False)
    await voice_category.set_permissions(tourney_role, read_messages=True, connect=True, speak=True)
    
    # Store tournament data
    data['tournaments'][tournament_id] = {
        'name': name,
        'status': 'registration',
        'max_teams': max_teams,
        'match_point_threshold': match_point,
        'entry_fee': entry_fee,
        'scheduled_date': tournament_datetime.isoformat(),
        'timezone': timezone,
        'teams': [],
        'matches': [],
        'created_at': datetime.now().isoformat(),
        'created_by': interaction.user.id,
        'guild_id': guild.id,
        'role_id': tourney_role.id,
        'category_id': tourney_category.id,
        'voice_category_id': voice_category.id,
        'channels': {
            'chat': chat_channel.id,
            'submit': submit_channel.id,
            'updates': updates_channel.id
        },
        'prize_pool': 0,
        'paid_teams': []
    }
    await save_and_sync(data)
    
    # Calculate potential prize pools
    prize_70 = int(max_teams * entry_fee * 0.70)  # 70% to winners
    prize_20 = int(max_teams * entry_fee * 0.20)  # 20% to second
    prize_10 = int(max_teams * entry_fee * 0.10)  # 10% to third
    
    # Create announcement embed
    embed = discord.Embed(
        title=f"🏆 NEW TOURNAMENT: {name.upper()}",
        description=(
            f"**Registration is NOW OPEN!**\n\n"
            f"Get your squad ready for battle!"
        ),
        color=COLORS['tournament']
    )
    
    embed.add_field(
        name="📅 Date & Time",
        value=f"**{tournament_datetime.strftime('%A, %B %d, %Y')}**\n{tournament_datetime.strftime('%I:%M %p')} {timezone}",
        inline=False
    )
    
    embed.add_field(name="🎮 Format", value="Warzone Resurgence Trios\nEWC Match Point System", inline=True)
    embed.add_field(name="👥 Max Teams", value=str(max_teams), inline=True)
    embed.add_field(name="🎯 Match Point", value=f"{match_point} points", inline=True)
    
    embed.add_field(
        name="💰 Entry Fee",
        value=f"**${entry_fee} per team**\n(${entry_fee/3:.2f} per player)",
        inline=True
    )
    
    embed.add_field(
        name="🏆 Prize Pool (if full)",
        value=f"🥇 1st: **${prize_70}**\n🥈 2nd: **${prize_20}**\n🥉 3rd: **${prize_10}**",
        inline=True
    )
    
    embed.add_field(
        name="📋 How to Register",
        value=(
            f"1. Use `/register_team` command\n"
            f"2. Pay ${entry_fee} via CashApp/Venmo/PayPal\n"
            f"3. Wait for payment confirmation\n"
            f"4. You'll get the {tourney_role.mention} role"
        ),
        inline=False
    )
    
    embed.add_field(
        name="⚔️ How to Win",
        value=(
            f"• 1 point per kill + placement bonus\n"
            f"• Reach {match_point} points = Match Point Eligible\n"
            f"• Win a match while eligible = **CHAMPION**"
        ),
        inline=False
    )
    
    embed.add_field(
        name="❓ Questions?",
        value="Use `/ask` or @mention me to ask anything about the tournament!",
        inline=False
    )
    
    embed.set_footer(text=f"Tournament ID: {tournament_id} | Created by {interaction.user.display_name}")
    
    # Send to announcements channel
    announcements = discord.utils.get(guild.text_channels, name="📢-announcements")
    pings_role = guild.get_role(data['server_config'].get(str(guild.id), {}).get('pings_role_id'))
    
    if announcements:
        ping_text = f"{pings_role.mention}" if pings_role else "@everyone"
        await announcements.send(f"{ping_text}\n\n🚨 **NEW TOURNAMENT ALERT!** 🚨", embed=embed)
    
    await interaction.followup.send(
        f"✅ Tournament **{name}** created!\n"
        f"📢 Announcement posted in {announcements.mention if announcements else 'announcements'}\n"
        f"🎮 Tournament channels created under **{tourney_category.name}**",
        embed=embed
    )

# ==================== TEAM REGISTRATION ====================
@bot.tree.command(name="register_team", description="Register your team for a tournament")
@app_commands.describe(
    tournament_id="Tournament ID (e.g., tourney_1)",
    team_name="Your team name",
    player1="Activision ID of player 1 (Captain)",
    player2="Activision ID of player 2",
    player3="Activision ID of player 3",
    stream1="Stream URL for player 1 (optional)",
    stream2="Stream URL for player 2 (optional)",
    stream3="Stream URL for player 3 (optional)"
)
async def register_team(
    interaction: discord.Interaction,
    tournament_id: str,
    team_name: str,
    player1: str,
    player2: str,
    player3: str,
    stream1: Optional[str] = None,
    stream2: Optional[str] = None,
    stream3: Optional[str] = None
):
    """Register a team for a tournament"""
    if tournament_id not in data['tournaments']:
        await interaction.response.send_message("❌ Invalid tournament ID!", ephemeral=True)
        return
    
    tournament = data['tournaments'][tournament_id]
    
    if tournament['status'] != 'registration':
        await interaction.response.send_message("❌ Registration is closed for this tournament!", ephemeral=True)
        return
    
    if len(tournament['teams']) >= tournament['max_teams']:
        await interaction.response.send_message("❌ Tournament is full!", ephemeral=True)
        return
    
    # Check for duplicate team names
    for tid in tournament['teams']:
        if data['teams'][tid]['name'].lower() == team_name.lower():
            await interaction.response.send_message("❌ Team name already taken!", ephemeral=True)
            return
    
    team_id = f"team_{len(data['teams']) + 1}"
    
    data['teams'][team_id] = {
        'name': team_name,
        'captain': interaction.user.id,
        'captain_name': interaction.user.display_name,
        'players': [player1, player2, player3],
        'discord_members': [interaction.user.id],  # Add other members later
        'tournament_id': tournament_id,
        'total_points': 0,
        'match_point_eligible': False,
        'matches_played': [],
        'streaks': {
            'current_win_streak': 0,
            'best_win_streak': 0,
            'current_kill_streak': 0,
            'placement_streak': 0
        },
        'streams': {
            'player1': stream1 or '',
            'player2': stream2 or '',
            'player3': stream3 or ''
        },
        'registered_at': datetime.now().isoformat(),
        'payment_status': 'pending',
        'payment_method': None,
        'payment_confirmed_by': None,
        'payment_confirmed_at': None
    }
    
    tournament['teams'].append(team_id)
    await save_and_sync(data)
    
    # Calculate current prize pool
    paid_count = len(tournament.get('paid_teams', []))
    current_pool = paid_count * tournament['entry_fee']
    potential_pool = len(tournament['teams']) * tournament['entry_fee']
    
    embed = discord.Embed(
        title="✅ TEAM REGISTERED!",
        description=f"**{team_name}** has been registered for **{tournament['name']}**",
        color=COLORS['success']
    )
    
    embed.add_field(name="🎮 Team ID", value=f"`{team_id}`", inline=True)
    embed.add_field(name="👑 Captain", value=interaction.user.mention, inline=True)
    embed.add_field(name="💰 Entry Fee", value=f"${tournament['entry_fee']}", inline=True)
    
    embed.add_field(
        name="👥 Roster",
        value=f"1. {player1}\n2. {player2}\n3. {player3}",
        inline=False
    )
    
    if stream1 or stream2 or stream3:
        streams_text = ""
        if stream1: streams_text += f"• {stream1}\n"
        if stream2: streams_text += f"• {stream2}\n"
        if stream3: streams_text += f"• {stream3}\n"
        embed.add_field(name="📺 Streams", value=streams_text, inline=False)
    
    embed.add_field(
        name="⚠️ PAYMENT REQUIRED",
        value=(
            f"Send **${tournament['entry_fee']}** to complete registration:\n"
            f"• **CashApp:** $YourCashApp\n"
            f"• **Venmo:** @YourVenmo\n"
            f"• **PayPal:** your@email.com\n\n"
            f"Include `{team_id}` in payment note!"
        ),
        inline=False
    )
    
    embed.add_field(
        name="📊 Tournament Status",
        value=f"Teams Registered: {len(tournament['teams'])}/{tournament['max_teams']}\nPaid Teams: {paid_count}\nPrize Pool: ${current_pool} (${potential_pool} potential)",
        inline=False
    )
    
    embed.set_footer(text="Your registration is PENDING until payment is confirmed.")
    
    await interaction.response.send_message(embed=embed)
    
    # Also post to payment verification channel
    guild = interaction.guild
    payment_channel = discord.utils.get(guild.text_channels, name="💵-payment-verification")
    if payment_channel:
        admin_embed = discord.Embed(
            title="💳 NEW REGISTRATION - AWAITING PAYMENT",
            description=f"**Team:** {team_name}\n**Captain:** {interaction.user.mention}",
            color=COLORS['warning']
        )
        admin_embed.add_field(name="Team ID", value=f"`{team_id}`", inline=True)
        admin_embed.add_field(name="Amount Due", value=f"${tournament['entry_fee']}", inline=True)
        admin_embed.add_field(name="Tournament", value=tournament['name'], inline=True)
        admin_embed.add_field(
            name="Confirm Payment",
            value=f"Use `/confirm_payment team_id:{team_id}` when received",
            inline=False
        )
        await payment_channel.send(embed=admin_embed)

# ==================== PAYMENT CONFIRMATION ====================
@bot.tree.command(name="confirm_payment", description="Confirm a team's payment (Admin only)")
@app_commands.describe(
    team_id="Team ID to confirm",
    payment_method="How they paid (CashApp, Venmo, PayPal, Cash)"
)
@app_commands.default_permissions(administrator=True)
async def confirm_payment(
    interaction: discord.Interaction,
    team_id: str,
    payment_method: str
):
    """Confirm team payment and assign tournament role"""
    if team_id not in data['teams']:
        await interaction.response.send_message("❌ Invalid team ID!", ephemeral=True)
        return
    
    team = data['teams'][team_id]
    tournament = data['tournaments'].get(team['tournament_id'])
    
    if not tournament:
        await interaction.response.send_message("❌ Tournament not found!", ephemeral=True)
        return
    
    if team['payment_status'] == 'confirmed':
        await interaction.response.send_message("⚠️ Payment already confirmed!", ephemeral=True)
        return
    
    # Update payment status
    team['payment_status'] = 'confirmed'
    team['payment_method'] = payment_method
    team['payment_confirmed_by'] = interaction.user.id
    team['payment_confirmed_at'] = datetime.now().isoformat()
    
    # Add to paid teams
    if 'paid_teams' not in tournament:
        tournament['paid_teams'] = []
    tournament['paid_teams'].append(team_id)
    
    # Update prize pool
    tournament['prize_pool'] = len(tournament['paid_teams']) * tournament['entry_fee']
    
    await save_and_sync(data)
    
    guild = interaction.guild
    
    # Assign tournament role to captain
    tourney_role = guild.get_role(tournament['role_id'])
    captain = guild.get_member(team['captain'])
    
    if tourney_role and captain:
        await captain.add_roles(tourney_role)
    
    # Create team voice channel
    voice_category = guild.get_channel(tournament.get('voice_category_id'))
    if voice_category:
        team_vc = await guild.create_voice_channel(
            f"🎤 {team['name']}",
            category=voice_category
        )
        team['voice_channel_id'] = team_vc.id
        await save_and_sync(data)
    
    # Send confirmation
    embed = discord.Embed(
        title="💰 PAYMENT CONFIRMED!",
        description=f"**{team['name']}** is now officially registered!",
        color=COLORS['success']
    )
    embed.add_field(name="Team ID", value=f"`{team_id}`", inline=True)
    embed.add_field(name="Payment Method", value=payment_method, inline=True)
    embed.add_field(name="Confirmed By", value=interaction.user.mention, inline=True)
    embed.add_field(
        name="📊 Prize Pool Update",
        value=f"**${tournament['prize_pool']}** ({len(tournament['paid_teams'])} teams paid)",
        inline=False
    )
    
    await interaction.response.send_message(embed=embed)
    
    # Notify captain
    if captain:
        try:
            dm_embed = discord.Embed(
                title=f"✅ You're IN! - {tournament['name']}",
                description=(
                    f"Your payment for **{team['name']}** has been confirmed!\n\n"
                    f"You now have access to the tournament channels.\n"
                    f"Good luck, Operator! 🎮"
                ),
                color=COLORS['success']
            )
            dm_embed.add_field(
                name="📅 Tournament Date",
                value=datetime.fromisoformat(tournament['scheduled_date']).strftime('%A, %B %d at %I:%M %p'),
                inline=False
            )
            await captain.send(embed=dm_embed)
        except:
            pass  # DMs might be disabled
    
    # Update confirmed teams channel
    confirmed_channel = discord.utils.get(guild.text_channels, name="✅-confirmed-teams")
    if confirmed_channel:
        team_embed = discord.Embed(
            title=f"✅ {team['name']}",
            description=f"Captain: {captain.mention if captain else team['captain_name']}",
            color=COLORS['military']
        )
        team_embed.add_field(
            name="Roster",
            value="\n".join([f"• {p}" for p in team['players']]),
            inline=False
        )
        await confirmed_channel.send(embed=team_embed)

# ==================== START TOURNAMENT ====================
@bot.tree.command(name="start_tournament", description="Start the tournament (close registration)")
@app_commands.describe(tournament_id="Tournament ID to start")
@app_commands.default_permissions(administrator=True)
async def start_tournament(interaction: discord.Interaction, tournament_id: str):
    """Start the tournament and send begin message"""
    if tournament_id not in data['tournaments']:
        await interaction.response.send_message("❌ Invalid tournament ID!", ephemeral=True)
        return
    
    tournament = data['tournaments'][tournament_id]
    tournament['status'] = 'active'
    tournament['started_at'] = datetime.now().isoformat()
    await save_and_sync(data)
    
    guild = interaction.guild
    
    # Get tournament role and channels
    tourney_role = guild.get_role(tournament['role_id'])
    updates_channel = guild.get_channel(tournament['channels'].get('updates'))
    
    paid_count = len(tournament.get('paid_teams', []))
    
    embed = discord.Embed(
        title=f"🚀 {tournament['name'].upper()} HAS BEGUN!",
        description=(
            f"**Registration is CLOSED!**\n\n"
            f"**{paid_count} TEAMS** are battling for **${tournament['prize_pool']}**!\n\n"
            f"May the best squad win! 🏆"
        ),
        color=COLORS['tournament']
    )
    
    embed.add_field(
        name="🎯 Objective",
        value=f"Reach **{tournament['match_point_threshold']} points** to become Match Point Eligible, then WIN a match!",
        inline=False
    )
    
    embed.add_field(
        name="📸 Submit Results",
        value="After each match, use `/submit_match` with your kills and placement",
        inline=False
    )
    
    embed.add_field(
        name="💰 Prize Pool",
        value=f"🥇 1st: **${int(tournament['prize_pool'] * 0.70)}**\n"
              f"🥈 2nd: **${int(tournament['prize_pool'] * 0.20)}**\n"
              f"🥉 3rd: **${int(tournament['prize_pool'] * 0.10)}**",
        inline=False
    )
    
    embed.set_footer(text="Good luck, Operators! 🎮")
    
    # Ping tournament participants
    if updates_channel:
        await updates_channel.send(f"{tourney_role.mention}\n\n🚨 **THE TOURNAMENT IS STARTING!** 🚨", embed=embed)
    
    # Also post in announcements
    announcements = discord.utils.get(guild.text_channels, name="📢-announcements")
    if announcements:
        await announcements.send(embed=embed)
    
    await interaction.response.send_message(f"✅ **{tournament['name']}** has started!", embed=embed)

# ==================== END TOURNAMENT ====================
@bot.tree.command(name="end_tournament", description="End tournament, announce winners, and clean up")
@app_commands.describe(
    tournament_id="Tournament ID to end",
    first_place="Team ID of 1st place",
    second_place="Team ID of 2nd place",
    third_place="Team ID of 3rd place"
)
@app_commands.default_permissions(administrator=True)
async def end_tournament(
    interaction: discord.Interaction,
    tournament_id: str,
    first_place: str,
    second_place: str,
    third_place: str
):
    """End tournament, announce winners, clean up channels"""
    await interaction.response.defer()
    
    if tournament_id not in data['tournaments']:
        await interaction.followup.send("❌ Invalid tournament ID!", ephemeral=True)
        return
    
    tournament = data['tournaments'][tournament_id]
    guild = interaction.guild
    
    # Validate teams
    teams_valid = all(tid in data['teams'] for tid in [first_place, second_place, third_place])
    if not teams_valid:
        await interaction.followup.send("❌ Invalid team ID(s)!", ephemeral=True)
        return
    
    first_team = data['teams'][first_place]
    second_team = data['teams'][second_place]
    third_team = data['teams'][third_place]
    
    # Calculate prizes
    prize_pool = tournament['prize_pool']
    first_prize = int(prize_pool * 0.70)
    second_prize = int(prize_pool * 0.20)
    third_prize = int(prize_pool * 0.10)
    
    # Update tournament status
    tournament['status'] = 'completed'
    tournament['ended_at'] = datetime.now().isoformat()
    tournament['results'] = {
        'first': {'team_id': first_place, 'prize': first_prize},
        'second': {'team_id': second_place, 'prize': second_prize},
        'third': {'team_id': third_place, 'prize': third_prize}
    }
    await save_and_sync(data)
    
    # Assign Champion role to winning team captain
    winner_role = guild.get_role(data['server_config'].get(str(guild.id), {}).get('winner_role_id'))
    first_captain = guild.get_member(first_team['captain'])
    if winner_role and first_captain:
        await first_captain.add_roles(winner_role)
    
    # Create victory embed
    embed = discord.Embed(
        title=f"🏆 {tournament['name'].upper()} - FINAL RESULTS 🏆",
        description=f"**THE TOURNAMENT HAS CONCLUDED!**\n\nCongratulations to all participants!",
        color=COLORS['gold']
    )
    
    embed.add_field(
        name="🥇 1ST PLACE",
        value=f"**{first_team['name']}**\n{first_team['total_points']} points\n💰 **${first_prize}**",
        inline=True
    )
    embed.add_field(
        name="🥈 2ND PLACE", 
        value=f"**{second_team['name']}**\n{second_team['total_points']} points\n💰 **${second_prize}**",
        inline=True
    )
    embed.add_field(
        name="🥉 3RD PLACE",
        value=f"**{third_team['name']}**\n{third_team['total_points']} points\n💰 **${third_prize}**",
        inline=True
    )
    
    embed.add_field(
        name="📊 Tournament Stats",
        value=(
            f"• Total Teams: {len(tournament['paid_teams'])}\n"
            f"• Total Matches: {len(tournament['matches'])}\n"
            f"• Prize Pool: ${prize_pool}"
        ),
        inline=False
    )
    
    embed.set_footer(text="Thank you for participating! See you in the next tournament!")
    
    # Post to announcements
    announcements = discord.utils.get(guild.text_channels, name="📢-announcements")
    if announcements:
        await announcements.send("🎊 **TOURNAMENT CONCLUDED!** 🎊", embed=embed)
    
    # Send to tournament channels before deleting
    updates_channel = guild.get_channel(tournament['channels'].get('updates'))
    tourney_role = guild.get_role(tournament['role_id'])
    
    if updates_channel:
        await updates_channel.send(f"{tourney_role.mention if tourney_role else ''}", embed=embed)
        await updates_channel.send("⚠️ **These channels will be deleted in 5 minutes.** Save any important information!")
    
    await interaction.followup.send(
        f"✅ Tournament ended! Results posted.\n"
        f"⏳ Channels will be deleted in 5 minutes.",
        embed=embed
    )
    
    # Wait 5 minutes then clean up
    await asyncio.sleep(300)  # 5 minutes
    
    # Delete tournament channels
    try:
        # Delete tournament category and channels
        category = guild.get_channel(tournament['category_id'])
        if category:
            for channel in category.channels:
                await channel.delete(reason="Tournament ended")
            await category.delete(reason="Tournament ended")
        
        # Delete voice category and channels
        voice_category = guild.get_channel(tournament.get('voice_category_id'))
        if voice_category:
            for channel in voice_category.channels:
                await channel.delete(reason="Tournament ended")
            await voice_category.delete(reason="Tournament ended")
        
        # Delete tournament role
        if tourney_role:
            await tourney_role.delete(reason="Tournament ended")
        
        # Delete team voice channels
        for tid in tournament['teams']:
            team = data['teams'].get(tid)
            if team and team.get('voice_channel_id'):
                vc = guild.get_channel(team['voice_channel_id'])
                if vc:
                    await vc.delete(reason="Tournament ended")
        
    except Exception as e:
        print(f"Error cleaning up tournament: {e}")
    
    # Log cleanup
    admin_channel = discord.utils.get(guild.text_channels, name="⚙️-admin-commands")
    if admin_channel:
        await admin_channel.send(f"✅ Tournament **{tournament['name']}** channels have been cleaned up.")

# ==================== MATCH SUBMISSION ====================
@bot.tree.command(name="submit_match", description="Submit your match results")
@app_commands.describe(
    team_id="Your team ID",
    kills="Total team kills",
    placement="Your placement (1-20)"
)
async def submit_match(
    interaction: discord.Interaction,
    team_id: str,
    kills: int,
    placement: int
):
    """Submit match results with auto-calculations"""
    if team_id not in data['teams']:
        await interaction.response.send_message("❌ Invalid team ID!", ephemeral=True)
        return
    
    team = data['teams'][team_id]
    tournament = data['tournaments'].get(team['tournament_id'])
    
    if not tournament or tournament['status'] != 'active':
        await interaction.response.send_message("❌ Tournament is not active!", ephemeral=True)
        return
    
    # Verify submitter is captain or admin
    if interaction.user.id != team['captain']:
        admin_role = interaction.guild.get_role(
            data['server_config'].get(str(interaction.guild.id), {}).get('admin_role_id')
        )
        if not admin_role or admin_role not in interaction.user.roles:
            await interaction.response.send_message("❌ Only the team captain can submit results!", ephemeral=True)
            return
    
    # Calculate points
    placement_bonus = PLACEMENT_MULTIPLIERS.get(placement, 0)
    total_points = kills + placement_bonus
    
    match_id = f"match_{len(team['matches_played']) + 1}"
    
    match_data = {
        'match_id': match_id,
        'kills': kills,
        'placement': placement,
        'points': total_points,
        'timestamp': datetime.now().isoformat()
    }
    
    team['matches_played'].append(match_data)
    old_points = team['total_points']
    team['total_points'] += total_points
    
    # Check for match point
    was_match_point = team['match_point_eligible']
    if team['total_points'] >= tournament['match_point_threshold'] and not team['match_point_eligible']:
        team['match_point_eligible'] = True
    
    # Update streaks
    if placement <= 3:
        team['streaks']['current_win_streak'] += 1
        team['streaks']['placement_streak'] += 1
        if team['streaks']['current_win_streak'] > team['streaks']['best_win_streak']:
            team['streaks']['best_win_streak'] = team['streaks']['current_win_streak']
    else:
        team['streaks']['current_win_streak'] = 0
    
    if kills >= 10:
        team['streaks']['current_kill_streak'] += 1
    else:
        team['streaks']['current_kill_streak'] = 0
    
    # Update leaderboards
    if 'leaderboards' not in data:
        data['leaderboards'] = {'highest_kill_match': [], 'total_kills': {}}
    
    # Highest kill match
    data['leaderboards']['highest_kill_match'].append({
        'team_id': team_id,
        'team_name': team['name'],
        'kills': kills,
        'placement': placement,
        'points': total_points,
        'match_id': match_id,
        'timestamp': datetime.now().isoformat()
    })
    data['leaderboards']['highest_kill_match'].sort(key=lambda x: x['kills'], reverse=True)
    data['leaderboards']['highest_kill_match'] = data['leaderboards']['highest_kill_match'][:20]
    
    # Total kills
    total_team_kills = sum(m['kills'] for m in team['matches_played'])
    data['leaderboards']['total_kills'][team_id] = {
        'team_name': team['name'],
        'total': total_team_kills,
        'matches': len(team['matches_played']),
        'avg_per_match': total_team_kills / len(team['matches_played'])
    }
    
    # Recent matches
    if 'recent_matches' not in data:
        data['recent_matches'] = []
    
    data['recent_matches'].insert(0, {
        'match_id': f"global_{len(data['recent_matches']) + 1}",
        'timestamp': datetime.now().isoformat(),
        'winner': team_id if placement == 1 else None,
        'results': [{
            'team_id': team_id,
            'kills': kills,
            'placement': placement,
            'points': total_points
        }]
    })
    data['recent_matches'] = data['recent_matches'][:50]
    
    await save_and_sync(data)
    
    # Create response embed
    embed = discord.Embed(
        title=f"📊 MATCH RECORDED - {team['name']}",
        color=COLORS['gold'] if placement == 1 else COLORS['military']
    )
    
    embed.add_field(name="🎯 Placement", value=f"#{placement}", inline=True)
    embed.add_field(name="💀 Kills", value=str(kills), inline=True)
    embed.add_field(name="📍 Placement Bonus", value=f"+{placement_bonus}", inline=True)
    embed.add_field(name="⭐ Points Earned", value=f"**+{total_points}**", inline=True)
    embed.add_field(name="📈 Total Points", value=f"**{team['total_points']}** ({old_points} → {team['total_points']})", inline=True)
    
    # Match point notification
    if team['match_point_eligible'] and not was_match_point:
        embed.add_field(
            name="⚡ MATCH POINT ACHIEVED!",
            value=f"**{team['name']}** can now WIN by getting 1st place!",
            inline=False
        )
    elif team['match_point_eligible']:
        embed.add_field(
            name="⚡ Status",
            value="MATCH POINT ELIGIBLE",
            inline=False
        )
    else:
        points_needed = tournament['match_point_threshold'] - team['total_points']
        embed.add_field(
            name="🎯 Until Match Point",
            value=f"{points_needed} points needed",
            inline=False
        )
    
    # Check for tournament win
    if team['match_point_eligible'] and placement == 1:
        embed.add_field(
            name="🏆🏆🏆 POTENTIAL WINNER! 🏆🏆🏆",
            value="Admin needs to verify and call `/end_tournament`!",
            inline=False
        )
    
    await interaction.response.send_message(embed=embed)
    
    # Post to live updates
    guild = interaction.guild
    updates_channel = guild.get_channel(tournament['channels'].get('updates'))
    if updates_channel:
        update_embed = discord.Embed(
            title=f"{'🏆 ' if placement == 1 else ''}Match Result: {team['name']}",
            description=f"#{placement} with {kills} kills → **+{total_points} points**",
            color=COLORS['gold'] if placement == 1 else COLORS['info']
        )
        update_embed.add_field(name="Total Points", value=f"**{team['total_points']}**", inline=True)
        
        if team['match_point_eligible']:
            update_embed.add_field(name="Status", value="⚡ MATCH POINT", inline=True)
        
        await updates_channel.send(embed=update_embed)

# ==================== STANDINGS ====================
@bot.tree.command(name="standings", description="View current tournament standings")
@app_commands.describe(tournament_id="Tournament ID to view")
async def standings(interaction: discord.Interaction, tournament_id: str):
    """Display tournament standings"""
    if tournament_id not in data['tournaments']:
        await interaction.response.send_message("❌ Invalid tournament ID!", ephemeral=True)
        return
    
    tournament = data['tournaments'][tournament_id]
    teams = [(tid, data['teams'][tid]) for tid in tournament['teams'] if tid in data['teams']]
    teams.sort(key=lambda x: x[1]['total_points'], reverse=True)
    
    embed = discord.Embed(
        title=f"🏆 {tournament['name']} - STANDINGS",
        description=f"Match Point: {tournament['match_point_threshold']} pts | Prize Pool: ${tournament.get('prize_pool', 0)}",
        color=COLORS['tournament']
    )
    
    for i, (tid, team) in enumerate(teams[:15], 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"#{i}"
        status = " ⚡" if team['match_point_eligible'] else ""
        
        streak_text = ""
        if team['streaks']['current_win_streak'] >= 2:
            streak_text = f" 🔥{team['streaks']['current_win_streak']}"
        
        total_kills = sum(m['kills'] for m in team['matches_played'])
        
        embed.add_field(
            name=f"{medal} {team['name']}{status}{streak_text}",
            value=f"**{team['total_points']} pts** | {len(team['matches_played'])} matches | {total_kills} kills",
            inline=False
        )
    
    embed.set_footer(text=f"Teams: {len(teams)} | Paid: {len(tournament.get('paid_teams', []))}")
    
    await interaction.response.send_message(embed=embed)

# ==================== TEAM STATS ====================
@bot.tree.command(name="team_stats", description="View detailed team statistics")
@app_commands.describe(team_id="Team ID to view")
async def team_stats(interaction: discord.Interaction, team_id: str):
    """Display detailed team stats"""
    if team_id not in data['teams']:
        await interaction.response.send_message("❌ Invalid team ID!", ephemeral=True)
        return
    
    team = data['teams'][team_id]
    tournament = data['tournaments'].get(team['tournament_id'], {})
    
    embed = discord.Embed(
        title=f"📊 {team['name']} - Team Stats",
        color=COLORS['military']
    )
    
    embed.add_field(name="🎮 Team ID", value=f"`{team_id}`", inline=True)
    embed.add_field(name="🏆 Tournament", value=tournament.get('name', 'N/A'), inline=True)
    embed.add_field(name="💰 Payment", value=team['payment_status'].upper(), inline=True)
    
    embed.add_field(
        name="👥 Roster",
        value="\n".join([f"• {p}" for p in team['players']]),
        inline=False
    )
    
    total_kills = sum(m['kills'] for m in team['matches_played'])
    avg_kills = total_kills / len(team['matches_played']) if team['matches_played'] else 0
    avg_placement = sum(m['placement'] for m in team['matches_played']) / len(team['matches_played']) if team['matches_played'] else 0
    
    embed.add_field(name="📈 Total Points", value=str(team['total_points']), inline=True)
    embed.add_field(name="🎯 Matches Played", value=str(len(team['matches_played'])), inline=True)
    embed.add_field(name="⚡ Match Point", value="YES" if team['match_point_eligible'] else "NO", inline=True)
    
    embed.add_field(name="💀 Total Kills", value=str(total_kills), inline=True)
    embed.add_field(name="📊 Avg Kills/Match", value=f"{avg_kills:.1f}", inline=True)
    embed.add_field(name="📍 Avg Placement", value=f"#{avg_placement:.1f}", inline=True)
    
    embed.add_field(
        name="🔥 Streaks",
        value=f"Current Win: {team['streaks']['current_win_streak']} | Best Win: {team['streaks']['best_win_streak']}",
        inline=False
    )
    
    # Recent matches
    if team['matches_played']:
        recent = team['matches_played'][-5:][::-1]  # Last 5, reversed
        recent_text = ""
        for m in recent:
            recent_text += f"#{m['placement']} | {m['kills']} kills | +{m['points']} pts\n"
        embed.add_field(name="📜 Recent Matches", value=recent_text, inline=False)
    
    await interaction.response.send_message(embed=embed)

# ==================== BOT READY ====================
@bot.event
async def on_ready():
    print(f'{bot.user} is now running!')
    print(f'Connected to {len(bot.guilds)} guild(s)')
    
    # Check Gemini API
    if GEMINI_API_KEY == 'YOUR_GEMINI_API_KEY_HERE':
        print("⚠️ WARNING: Gemini API key not configured! AI features will be disabled.")
    else:
        print("✅ Gemini API key configured - AI features enabled!")
    
    # Add persistent views
    bot.add_view(RoleSelectView())
    
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Error syncing commands: {e}")

# ==================== HELP COMMAND ====================
@bot.tree.command(name="help", description="Show all bot commands")
async def help_command(interaction: discord.Interaction):
    """Display help menu"""
    embed = discord.Embed(
        title="⚔️ ARCANE TOURNEYS BOT",
        description="**Warzone Resurgence Trios - EWC Match Point Format**",
        color=COLORS['military']
    )
    
    embed.add_field(
        name="🤖 AI Features",
        value=(
            "`/ask` - Ask the AI assistant anything!\n"
            "`@mention` - Mention the bot to ask questions\n"
            "AI-powered personalized welcome messages"
        ),
        inline=False
    )
    
    embed.add_field(
        name="🔧 Admin Commands",
        value=(
            "`/setup_server` - Initial server setup\n"
            "`/setup_roles` - Create role selection message\n"
            "`/create_tournament` - Create new tournament\n"
            "`/confirm_payment` - Confirm team payment\n"
            "`/start_tournament` - Begin tournament\n"
            "`/end_tournament` - End & cleanup tournament\n"
            "`/sync_website` - Force sync to website"
        ),
        inline=False
    )
    
    embed.add_field(
        name="👥 Player Commands",
        value=(
            "`/register_team` - Register for tournament\n"
            "`/submit_match` - Submit match results\n"
            "`/standings` - View leaderboard\n"
            "`/team_stats` - View team details"
        ),
        inline=False
    )
    
    embed.add_field(
        name="💰 Entry & Prizes",
        value=(
            f"• Entry Fee: ${ENTRY_FEE} per team\n"
            f"• 🥇 1st: 70% of prize pool\n"
            f"• 🥈 2nd: 20% of prize pool\n"
            f"• 🥉 3rd: 10% of prize pool"
        ),
        inline=False
    )
    
    embed.add_field(
        name="🎯 Scoring",
        value=(
            "• 1 point per kill\n"
            "• Placement bonus (1st=+15, 2nd=+12, etc.)\n"
            f"• Reach {MATCH_POINT_THRESHOLD} pts = Match Point\n"
            "• WIN while at Match Point = Champion!"
        ),
        inline=False
    )
    
    await interaction.response.send_message(embed=embed)

# ==================== WEBSITE SYNC COMMAND ====================
@bot.tree.command(name="sync_website", description="Force sync tournament data to the website")
@app_commands.default_permissions(administrator=True)
async def sync_website(interaction: discord.Interaction):
    """Manually trigger website sync"""
    await interaction.response.defer(ephemeral=True)
    
    success, message = await sync_to_github(data)
    
    if success:
        embed = discord.Embed(
            title="✅ Website Synced",
            description="Tournament data pushed to GitHub → Netlify will auto-deploy",
            color=COLORS['success']
        )
        embed.add_field(name="Status", value="Live data updated", inline=False)
        embed.set_footer(text=f"Synced at {datetime.now().strftime('%I:%M %p')}")
    else:
        embed = discord.Embed(
            title="⚠️ Sync Issue",
            description=message,
            color=COLORS['warning']
        )
        if "not configured" in message.lower():
            embed.add_field(
                name="Setup Required",
                value="Add your GitHub token and repo to the bot config.",
                inline=False
            )
    
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="sync_status", description="Check website sync configuration")
@app_commands.default_permissions(administrator=True)
async def sync_status(interaction: discord.Interaction):
    """Check sync configuration status"""
    embed = discord.Embed(
        title="🔄 Website Sync Status",
        color=COLORS['info']
    )
    
    # Check configuration
    github_token_configured = bool(GITHUB_TOKEN)
    repo_configured = bool(GITHUB_REPO)
    
    embed.add_field(
        name="GitHub Token",
        value="✅ Configured" if github_token_configured else "❌ Not set",
        inline=True
    )
    embed.add_field(
        name="Repository",
        value=f"✅ {GITHUB_REPO}" if repo_configured else "❌ Not set",
        inline=True
    )
    embed.add_field(
        name="Auto-Sync",
        value="✅ Enabled" if ENABLE_AUTO_SYNC else "❌ Disabled",
        inline=True
    )
    
    if github_token_configured and repo_configured:
        embed.add_field(
            name="Status",
            value="Ready. Data syncs to GitHub on every update.\nNetlify auto-deploys from GitHub.",
            inline=False
        )
    else:
        embed.add_field(
            name="Setup Instructions",
            value=(
                "1. Create a GitHub repo with your website files\n"
                "2. GitHub → Settings → Developer Settings → Personal Access Tokens\n"
                "3. Generate token with 'repo' scope\n"
                "4. Connect repo to Netlify (Import from Git)\n"
                "5. Add token and repo name to bot config"
            ),
            inline=False
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ==================== RUN THE BOT ====================
if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        raise RuntimeError("DISCORD_BOT_TOKEN is required")
    bot.run(DISCORD_BOT_TOKEN)
