# Spotify Now Playing Bot

A Telegram bot that shares your currently playing Spotify track via inline queries.

## Setup

### 1. Install dependencies

Install dependencies with [uv](https://github.com/astral-sh/uv):

```bash
uv sync
```

### 2. Create a Telegram Bot

1. Open Telegram and search for [@BotFather](https://t.me/botfather)
2. Send `/newbot` and follow the prompts to create your bot
3. You'll receive a **bot token** that looks like: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`
4. Send `/setinline` to BotFather and select your bot to enable inline mode
5. Save the bot token for later

### 3. Create a Spotify App

1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Log in with your Spotify account
3. Click "Create app"
4. Fill in the details:
   - **App name**: Choose any name (e.g., "Now Playing Bot")
   - **App description**: Any description
   - **Redirect URI**: `https://your-domain.com/spotify/callback` (replace with your actual domain)
5. Accept the terms and create the app
6. Click "Settings" to view your **Client ID** and **Client Secret**
7. Save both credentials for later

### 4. Generate security keys

Generate a secret key for encryption:

```bash
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Generate a webhook secret token:

```bash
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 5. Create a `.env` file

Create a `.env` file with all the credentials:

```env
ENVIRONMENT=production
LOG_LEVEL=INFO
APP_URL=https://your-domain.com
APP_SECRET=<generated-from-step-4>
BOT_TOKEN=<from-step-2-botfather>
BOT_WEBHOOK_SECRET=<generated-from-step-4>
SPOTIFY_CLIENT_ID=<from-step-3-spotify-dashboard>
SPOTIFY_CLIENT_SECRET=<from-step-3-spotify-dashboard>
DATABASE_URL=postgresql://user:password@localhost/dbname
```

Configuration notes:
- `ENVIRONMENT`: Can be `development`, `production`, or `test` (defaults to `development`)
- `LOG_LEVEL`: Logging level - `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` (defaults to `INFO`)
- `APP_URL`: Must be publicly accessible for Telegram webhooks to work
- `DATABASE_URL`: Optional, defaults to SQLite (`sqlite:///database.db`). For production, use PostgreSQL

### 6. Run database migrations

```bash
uv run alembic upgrade head
```

### 7. Deploy the bot

#### Development

For local development, you'll need to expose your local server to the internet for Telegram webhooks to work. Use a tool like [ngrok](https://ngrok.com/):

```bash
# Start ngrok in a separate terminal
ngrok http 8000

# Update APP_URL in .env to your ngrok URL (e.g., https://abc123.ngrok.io)
# Then start the development server
uv run fastapi dev --entrypoint app.main:app --host 0.0.0.0
```

#### Production

For production deployment, use a proper web server and ensure your domain is configured correctly:

```bash
uv run fastapi run --entrypoint app.main:app --host 0.0.0.0 --port 8000
```

Make sure your server is accessible at the `APP_URL` you configured in the `.env` file.

## Optional: Error Tracking with Sentry

To enable error tracking with Sentry, add your DSN to the `.env` file:

```env
SENTRY_DSN=your-sentry-dsn-here
```

The bot will work fine without Sentry configured - it's completely optional.

## Development

Run all checks before committing:

```bash
bash scripts/check.sh
```

This runs:

- `ruff check` - Linting
- `ruff format` - Code formatting
- `ty check` - Type checking
- `pytest` - Tests
- `alembic check` - Migration validation

## Usage

1. Start the bot with `/start`
2. Login with your Spotify account
3. Use the inline query (`@botname` in any chat) to share your current track
