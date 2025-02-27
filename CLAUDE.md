# ManheimTelegram Bot Commands

## Run Commands
- Start bot: `python bot.py`
- Install dependencies: `pip install -r requirements.txt`
- Environment setup: Create `.env` file with `TELEGRAM_BOT_TOKEN`, `MANHEIM_CLIENT_ID`, `MANHEIM_CLIENT_SECRET`, and `USE_MANHEIM_UAT`

## Code Style Guidelines
- **Naming**: Use snake_case for variables/functions, UPPER_CASE for constants
- **Imports**: Group standard library imports first, then third-party, then local
- **Formatting**: 4-space indentation, max line length ~100 characters
- **Error Handling**: Use try-except blocks with specific exception types and logging
- **Typing**: Type hints are encouraged but not required
- **Logging**: Use the Python logging module for all logging needs

## API Usage
- Always check API token validity before requests
- Use environment variables for sensitive credentials
- Handle API errors with appropriate error messages to users