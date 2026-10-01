# ArcaneTourneys

A Discord-operated tournament system with a public competition site for registrations, standings, match results, streams, and leaderboards.

> This repository is an early public prototype. Active development continued in a newer private site repository with Supabase-backed identity and additional tournament formats.

## What it demonstrates

- Discord slash-command workflows for tournament administration
- Team registration, payments, match reporting, standings, and leaderboards
- Sanitized transformation of private bot state into public website data
- Static competition pages suitable for Git-based hosting
- Optional GitHub-to-Netlify publishing workflow
- AI-assisted administrative responses through a provider API

## Architecture

```text
Discord participants and organizers
              |
              v
      Python Discord bot
       |              |
       | private      | sanitized public projection
       v              v
tournament_data.json  website_data.json
                             |
                             v
                 static tournament website
```

The bot's working data and the website's public data are separate by design. A production deployment should store private state in a protected database and publish only the fields required by the public site.

## Repository layout

```text
Tourney/
  warzone_tournament_bot_v2.py  Discord bot and tournament logic
  tournament_data.json          Empty development data shape
  index.html                    Tournament landing page
  standings.html                Standings and leaderboard view
  streams.html                  Participant stream directory
  rules.html                    Competition rules
```

## Local setup

Requires Python 3.10+.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install discord.py aiohttp

$env:DISCORD_BOT_TOKEN="replace-me"
$env:GEMINI_API_KEY="replace-me"       # optional
$env:GITHUB_TOKEN="replace-me"         # optional publishing integration
$env:GITHUB_REPO="owner/site-repo"     # optional publishing integration
$env:ENABLE_AUTO_SYNC="false"

Set-Location Tourney
python warzone_tournament_bot_v2.py
```

Never commit real bot, AI-provider, or GitHub credentials. Restrict token scopes to the minimum permissions required.

## Current status and limitations

- This public repository is a portfolio snapshot, not a hosted production service.
- JSON-file persistence is appropriate for a prototype, not concurrent production traffic.
- The optional GitHub publishing path should use a narrowly scoped token or GitHub App in production.
- Payment fields represent workflow state; this repository does not process card payments.
- The active platform later expanded into separate bot and site components with Supabase authentication.

## Portfolio highlights

This project shows product design across community operations, bot commands, data modeling, public/private data boundaries, responsive web presentation, and deployment automation.

