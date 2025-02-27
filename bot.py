import os
import logging
import requests
import json
import io
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, 
    filters, CallbackQueryHandler, ConversationHandler
)

# Load environment variables
load_dotenv()

# Configure logging with more comprehensive setup
log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'bot.log')

# Create a file handler that logs even debug messages
file_handler = logging.FileHandler(log_file)
file_handler.setLevel(logging.DEBUG)

# Create a console handler with a higher log level
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# Create formatter and add it to the handlers
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# Configure root logger
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[file_handler, console_handler]
)

logger = logging.getLogger(__name__)
logger.info("Logger initialized")

# Manheim API configuration
MANHEIM_CLIENT_ID = os.getenv("MANHEIM_CLIENT_ID")
MANHEIM_CLIENT_SECRET = os.getenv("MANHEIM_CLIENT_SECRET")

# Use UAT (test) environment if specified, otherwise use production
USE_UAT = os.getenv("USE_MANHEIM_UAT", "False").lower() in ("true", "1", "t")

if USE_UAT:
    MANHEIM_BASE_URL = "https://uat.api.manheim.com"
    MANHEIM_TOKEN_URL = "https://uat.api.manheim.com/oauth2/token"
else:
    MANHEIM_BASE_URL = "https://api.manheim.com"
    MANHEIM_TOKEN_URL = "https://api.manheim.com/oauth2/token"

MANHEIM_VALUATIONS_URL = f"{MANHEIM_BASE_URL}/valuations/vin/{{vin}}"
MANHEIM_YMM_URL = f"{MANHEIM_BASE_URL}/valuations/years/{{year}}/makes/{{make}}/models/{{model}}"

# Token storage
token_data = {
    "access_token": None,
    "expires_at": None
}

def get_manheim_token():
    """Get a new OAuth token for Manheim API access."""
    global token_data
    
    # Check if credentials are properly configured
    if not MANHEIM_CLIENT_ID or not MANHEIM_CLIENT_SECRET:
        logger.error("Manheim API credentials not properly configured")
        return None
    
    # Check if we have a valid token
    now = datetime.now()
    if (token_data["access_token"] and token_data["expires_at"] 
            and now < token_data["expires_at"]):
        return token_data["access_token"]
    
    # Request new token
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    data = {
        "grant_type": "client_credentials",
        "client_id": MANHEIM_CLIENT_ID,
        "client_secret": MANHEIM_CLIENT_SECRET
    }
    
    try:
        logger.info("Requesting new Manheim API token")
        response = requests.post(MANHEIM_TOKEN_URL, headers=headers, data=data, timeout=10)
        response.raise_for_status()
        
        token_info = response.json()
        if "access_token" not in token_info:
            logger.error("No access_token in Manheim API response")
            return None
            
        token_data["access_token"] = token_info["access_token"]
        # Set expiry time (typically 1 hour, but subtract 5 minutes for safety)
        expires_in_seconds = token_info.get("expires_in", 3600) - 300
        token_data["expires_at"] = now + timedelta(seconds=expires_in_seconds)
        
        logger.info("Successfully obtained new Manheim API token")
        return token_data["access_token"]
    
    except requests.exceptions.Timeout:
        logger.error("Timeout while connecting to Manheim API for token")
        return None
    except requests.exceptions.ConnectionError:
        logger.error("Connection error while connecting to Manheim API")
        return None
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error from Manheim API: {e.response.status_code} - {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"Error getting Manheim token: {e}")
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    await update.message.reply_text(
        "🚘 *Welcome to Vehicle Auction Bot!*\n\n"
        "*Available commands:*\n"
        "• `/vin [VIN]` - Get auction data for a VIN\n"
        "• `/ymm [Year] [Make] [Model]` - Get data by Year/Make/Model\n"
        "• `/history` - View your recent lookups\n\n"
        "Type `/help` for detailed examples and advanced options",
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    await update.message.reply_text(
        "🚘 *Vehicle Auction Bot - Help Guide*\n\n"
        "*VIN Lookup Options:*\n"
        "• Basic: `/vin 1HGCM82633A123456`\n"
        "• With subseries: `/vin 1HGCM82633A123456 SE`\n"
        "• With subseries & transmission: `/vin 1HGCM82633A123456 SE AUTO`\n"
        "• Advanced: `/vin WBA3C1C5XFP853102 color=WHITE grade=3.5 odometer=20000 region=NE`\n"
        "• Historical: `/vin 1HGCM82633A123456 date=2023-10-15`\n\n"
        
        "*Parameter Options:*\n"
        "• `color` - WHITE, BLACK, SILVER, etc.\n"
        "• `grade` - 1.0 to 5.0 (condition grade)\n"
        "• `odometer` - Mileage in miles\n"
        "• `region` - NE, SE, MW, SW, W\n"
        "• `date` - YYYY-MM-DD format (historical valuation)\n\n"
        
        "*Year/Make/Model Lookup:*\n"
        "• `/ymm 2020 Honda Accord`\n"
        "• With date: `/ymm 2020 Honda Accord date=2023-05-01`\n\n"
        
        "*History and Previous Lookups:*\n"
        "• `/history` - View your 10 most recent lookups\n"
        "• `/history VIN` - View only VIN lookups\n"
        "• `/history YMM` - View only Year/Make/Model lookups\n\n"
        
        "*Interactive Features:*\n"
        "• 📈 *Price Trend Charts* - Generate visual price trends for any vehicle\n"
        "• 🔍 *Transaction Filtering* - Filter auction data by grade, mileage, and date\n"
        "• 📄 *Pagination* - Navigate through large data sets with page controls\n\n"
        
        "*Testing Example:*\n"
        "• Test VIN (UAT): `WBA3C1C5XFP853102`\n\n"
        
        "💡 After a search, use the interactive 'Refine Valuation' button to adjust parameters with a user-friendly interface.\n"
        "💡 Date lookups show how vehicle values change over time. Dates must be after 2018-10-08.",
        parse_mode="Markdown"
    )

def validate_vin(vin):
    """
    Validate a Vehicle Identification Number (VIN)
    
    Args:
        vin (str): The VIN to validate
        
    Returns:
        tuple: (bool, str) whether valid and error message if not
    """
    if not vin:
        return False, "VIN cannot be empty"
    
    # VINs should be 17 characters for modern vehicles (since 1981)
    if len(vin) != 17:
        return False, "VIN must be exactly 17 characters"
    
    # VINs should be alphanumeric and not contain I, O, or Q to avoid confusion
    invalid_chars = set(c for c in vin if not c.isalnum() or c in "IOQ")
    if invalid_chars:
        return False, f"VIN contains invalid characters: {', '.join(invalid_chars)}"
    
    return True, ""

def get_vin_valuation(vin, subseries=None, transmission=None, **query_params):
    """
    Get valuation data for a specific VIN from Manheim API.
    
    Args:
        vin (str): The Vehicle Identification Number
        subseries (str, optional): Vehicle subseries for more specific valuation
        transmission (str, optional): Transmission type for more specific valuation
                                     (requires subseries to be specified)
        **query_params: Additional query parameters such as:
            - color (str): Vehicle color (e.g., "WHITE", "BLACK")
            - grade (float/str): Vehicle condition grade (e.g., "3.5", "4.0")
            - odometer (int): Vehicle mileage
            - region (str): Geographic region (e.g., "NE", "SE", "MW", "SW", "W")
            - date (str): Date for historical valuation (YYYY-MM-DD format)
    
    Returns:
        dict: Valuation data or None if not found/error
    """
    # Validate VIN
    is_valid, error_msg = validate_vin(vin)
    if not is_valid:
        logger.error(f"Invalid VIN: {error_msg} - {vin}")
        return None
    
    # Validate query parameters
    valid_regions = {"NE", "SE", "MW", "SW", "W"}
    if "region" in query_params and query_params["region"] not in valid_regions:
        logger.warning(f"Invalid region: {query_params['region']}. Must be one of {valid_regions}")
        query_params["region"] = None
        
    # Validate date parameter
    if "date" in query_params:
        date_str = query_params["date"]
        try:
            # Check if date is in correct format
            datetime.strptime(date_str, "%Y-%m-%d")
            
            # Check if date is after minimum allowed date (2018-10-08)
            min_date = datetime.strptime("2018-10-08", "%Y-%m-%d")
            requested_date = datetime.strptime(date_str, "%Y-%m-%d")
            
            if requested_date < min_date:
                logger.warning(f"Date too early: {date_str}. Must be on or after 2018-10-08")
                query_params["date"] = None
                
            # Check if date is in the future
            today = datetime.now()
            if requested_date > today:
                logger.warning(f"Future date: {date_str}. Must be on or before today's date")
                query_params["date"] = None
                
        except ValueError:
            logger.warning(f"Invalid date format: {date_str}. Must be in YYYY-MM-DD format")
            query_params["date"] = None
    
    if "grade" in query_params:
        try:
            grade_value = query_params["grade"]
            
            # Handle different grade formats
            if isinstance(grade_value, (int, float)):
                # If already a number, check if it's using the API format (10-50) or decimal format (1.0-5.0)
                if grade_value > 5 and grade_value <= 50:
                    # Already in API format (10-50)
                    if not 10 <= grade_value <= 50:
                        logger.warning(f"Grade out of range: {grade_value}. Must be between 10 and 50")
                        query_params["grade"] = None
                else:
                    # In decimal format (1.0-5.0), convert to API format (10-50)
                    if not 0 <= grade_value <= 5:
                        logger.warning(f"Grade out of range: {grade_value}. Must be between 0 and 5")
                        query_params["grade"] = None
                    else:
                        # Convert to API integer format
                        query_params["grade"] = int(grade_value * 10)
            else:
                # Try to convert string to number
                float_grade = float(grade_value)
                if float_grade > 5 and float_grade <= 50:
                    # Already in API format (10-50)
                    query_params["grade"] = int(float_grade)
                else:
                    # Convert from decimal (1.0-5.0) to API format (10-50)
                    if 0 <= float_grade <= 5:
                        query_params["grade"] = int(float_grade * 10)
                    else:
                        logger.warning(f"Grade out of range: {float_grade}. Must be between 0 and 5")
                        query_params["grade"] = None
                        
        except (ValueError, TypeError):
            logger.warning(f"Invalid grade value: {query_params['grade']}")
            query_params["grade"] = None
    
    if "odometer" in query_params:
        try:
            # Ensure odometer is a positive integer
            odometer = int(query_params["odometer"])
            if odometer < 0:
                logger.warning(f"Negative odometer value: {odometer}")
                query_params["odometer"] = None
            elif odometer > 999999:
                logger.warning(f"Unrealistic odometer value: {odometer}")
                query_params["odometer"] = None
            else:
                query_params["odometer"] = odometer
        except (ValueError, TypeError):
            logger.warning(f"Invalid odometer value: {query_params['odometer']}")
            query_params["odometer"] = None
    
    # Get authentication token
    token = get_manheim_token()
    if not token:
        logger.error("Failed to get authentication token")
        return None
    
    # Construct URL based on provided parameters
    if subseries and transmission:
        url = f"{MANHEIM_VALUATIONS_URL.format(vin=vin)}/{subseries}/{transmission}"
    elif subseries:
        url = f"{MANHEIM_VALUATIONS_URL.format(vin=vin)}/{subseries}"
    else:
        url = MANHEIM_VALUATIONS_URL.format(vin=vin)
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }
    
    # Filter out None values from query parameters
    params = {k: v for k, v in query_params.items() if v is not None}
    
    try:
        logger.info(f"Fetching valuation data for VIN: {vin}")
        response = requests.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        
        data = response.json()
        
        # Validate response data
        if not data:
            logger.warning(f"Empty response for VIN: {vin}")
            return None
            
        # Check if the response has the expected structure
        if "vehicle" not in data:
            logger.warning(f"Unexpected API response format for VIN: {vin} - missing vehicle data")
            
        logger.info(f"Successfully retrieved valuation data for VIN: {vin}")
        return data
        
    except requests.exceptions.Timeout:
        logger.error(f"Timeout while fetching data for VIN: {vin}")
        return None
    except requests.exceptions.ConnectionError:
        logger.error(f"Connection error while fetching data for VIN: {vin}")
        return None
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logger.warning(f"No data found for VIN: {vin}")
            return None
        logger.error(f"HTTP error fetching VIN data: {e.response.status_code} - {e.response.text}")
        return None
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON response for VIN: {vin}")
        return None
    except Exception as e:
        logger.error(f"Error fetching VIN data: {e}")
        return None

# State definitions for conversation
CHOOSING_COLOR, CHOOSING_GRADE, CHOOSING_ODOMETER, CHOOSING_REGION = range(4)

# Data storage for conversation context and history
user_data_dict = {}

# History cache to store previous lookups
# Structure: {user_id: [{'type': 'vin|ymm', 'query': VIN or YMM dict, 'data': API response, 'timestamp': datetime}]}
history_cache = {}

async def vin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get auction data for a specific VIN with optional parameters."""
    if not context.args:
        await update.message.reply_text(
            "❓ *Please provide a VIN*\n\n"
            "*Examples:*\n"
            "• `/vin 1HGCM82633A123456`\n"
            "• `/vin 1HGCM82633A123456 SE`\n"
            "• `/vin WBA3C1C5XFP853102 color=WHITE grade=3.5 odometer=20000`\n"
            "• `/vin 1HGCM82633A123456 date=2023-05-15`\n\n"
            "Type `/help` for more details and options.",
            parse_mode="Markdown"
        )
        return

    # Parse arguments
    vin = context.args[0].upper()  # Convert VIN to uppercase for consistency
    
    # Validate VIN format before proceeding
    is_valid, error_msg = validate_vin(vin)
    if not is_valid:
        await update.message.reply_text(
            f"❌ *Invalid VIN*: {error_msg}\n\n"
            f"VIN provided: `{vin}`\n\n"
            "Please provide a valid 17-character VIN.",
            parse_mode="Markdown"
        )
        return
    
    subseries = None
    transmission = None
    query_params = {}
    
    # Check if we have keyword arguments (containing '=')
    has_keyword_args = any('=' in arg for arg in context.args[1:])
    
    if has_keyword_args:
        # Process as keyword arguments
        for arg in context.args[1:]:
            if '=' in arg:
                key, value = arg.split('=', 1)
                key = key.lower()  # Normalize keys to lowercase
                
                # Validate and convert parameter values
                if key == 'color':
                    value = value.upper()  # Normalize colors to uppercase
                    
                elif key == 'grade':
                    try:
                        float_value = float(value)
                        if not 0 <= float_value <= 5:
                            await update.message.reply_text(
                                f"⚠️ *Warning*: Grade must be between 0 and 5. Using default value.",
                                parse_mode="Markdown"
                            )
                            continue
                        # Convert decimal grade (e.g., 3.5) to integer format (e.g., 35) for API
                        value = int(float_value * 10)
                    except ValueError:
                        await update.message.reply_text(
                            f"⚠️ *Warning*: Invalid grade '{value}'. Must be a number between 0 and 5. Using default value.",
                            parse_mode="Markdown"
                        )
                        continue
                        
                elif key == 'date':
                    # Validate date format (YYYY-MM-DD)
                    try:
                        # Parse date to validate format
                        requested_date = datetime.strptime(value, "%Y-%m-%d")
                        
                        # Check if date is after minimum allowed date (2018-10-08)
                        min_date = datetime.strptime("2018-10-08", "%Y-%m-%d")
                        if requested_date < min_date:
                            await update.message.reply_text(
                                f"⚠️ *Warning*: Date must be on or after 2018-10-08. Using current date.",
                                parse_mode="Markdown"
                            )
                            continue
                            
                        # Check if date is in the future
                        if requested_date > datetime.now():
                            await update.message.reply_text(
                                f"⚠️ *Warning*: Date cannot be in the future. Using current date.",
                                parse_mode="Markdown"
                            )
                            continue
                            
                    except ValueError:
                        await update.message.reply_text(
                            f"⚠️ *Warning*: Invalid date format '{value}'. Must be in YYYY-MM-DD format. Using current date.",
                            parse_mode="Markdown"
                        )
                        continue
                        
                elif key == 'odometer':
                    try:
                        value = int(value)
                        if value < 0 or value > 999999:
                            await update.message.reply_text(
                                f"⚠️ *Warning*: Invalid mileage value. Using default value.",
                                parse_mode="Markdown"
                            )
                            continue
                    except ValueError:
                        await update.message.reply_text(
                            f"⚠️ *Warning*: Invalid mileage '{value}'. Must be a number. Using default value.",
                            parse_mode="Markdown"
                        )
                        continue
                        
                elif key == 'region':
                    value = value.upper()
                    valid_regions = {"NE", "SE", "MW", "SW", "W"}
                    if value not in valid_regions:
                        await update.message.reply_text(
                            f"⚠️ *Warning*: Invalid region '{value}'. Must be one of: NE, SE, MW, SW, W. Using default value.",
                            parse_mode="Markdown"
                        )
                        continue
                
                # Add validated parameter to query
                query_params[key] = value
    else:
        # Process as positional arguments (subseries, transmission)
        if len(context.args) >= 2:
            subseries = context.args[1]
        
        if len(context.args) >= 3:
            transmission = context.args[2]
    
    # Inform user of the search with a cleaner message
    params_list = []
    if subseries:
        params_list.append(f"Subseries: {subseries}")
    if transmission:
        params_list.append(f"Transmission: {transmission}")
    for key, value in query_params.items():
        params_list.append(f"{key.capitalize()}: {value}")
    
    params_text = ", ".join(params_list)
    if params_text:
        search_message = f"🔍 *Searching for VIN:* `{vin}`\n*Parameters:* {params_text}"
    else:
        search_message = f"🔍 *Searching for VIN:* `{vin}`"
    
    await update.message.reply_text(search_message + "...", parse_mode="Markdown")
    
    try:
        # Get vehicle data from Manheim API
        data = get_vin_valuation(vin, subseries, transmission, **query_params)
        
        if not data:
            await update.message.reply_text(f"❌ *No auction data found for VIN:* `{vin}`", parse_mode="Markdown")
            return
            
        # Format and send the response with potential pagination
        MAX_MESSAGE_LENGTH = 4000  # Slightly less than Telegram's limit to accommodate markdown
        formatted_data = format_auction_data(data)
        
        # Check if we need pagination based on message length
        if len(formatted_data["message"]) > MAX_MESSAGE_LENGTH:
            # First message with pagination details
            await update.message.reply_text(
                f"📊 *Auction data for VIN:* `{vin}` (1/{formatted_data['total_pages']})",
                parse_mode="Markdown"
            )
            
            # Send paged messages
            for page in range(1, formatted_data['total_pages'] + 1):
                page_data = format_auction_data(data, MAX_MESSAGE_LENGTH, page)
                
                # Create pagination controls if needed
                if page_data['total_pages'] > 1:
                    # Add pagination controls as inline keyboard
                    keyboard = []
                    pagination_row = []
                    
                    if page > 1:
                        pagination_row.append(InlineKeyboardButton("« Prev", callback_data=f"page:{vin}:{page-1}"))
                    
                    pagination_row.append(InlineKeyboardButton(f"{page}/{page_data['total_pages']}", callback_data="noop"))
                    
                    if page < page_data['total_pages']:
                        pagination_row.append(InlineKeyboardButton("Next »", callback_data=f"page:{vin}:{page+1}"))
                    
                    keyboard.append(pagination_row)
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.message.reply_text(
                        page_data['message'],
                        parse_mode="Markdown",
                        reply_markup=reply_markup
                    )
                else:
                    await update.message.reply_text(
                        page_data['message'],
                        parse_mode="Markdown"
                    )
        else:
            # No pagination needed, send as one message
            await update.message.reply_text(formatted_data["message"], parse_mode="Markdown")
        
        # Store data for potential refinement and transaction viewing
        user_id = update.effective_user.id
        user_data_dict[user_id] = {
            'vin': vin,
            'subseries': subseries,
            'transmission': transmission,
            'params': query_params,
            'data': data  # Store full data response
        }
        
        # Add to history cache
        if user_id not in history_cache:
            history_cache[user_id] = []
            
        # Add the new lookup to the start of the list (most recent first)
        history_entry = {
            'type': 'vin',
            'query': {
                'vin': vin,
                'subseries': subseries,
                'transmission': transmission,
                'params': query_params.copy()
            },
            'data': data,
            'timestamp': datetime.now()
        }
        
        # Add special flag if this is a historical lookup
        if 'date' in query_params:
            history_entry['historical'] = True
            
        history_cache[user_id].insert(0, history_entry)
        
        # Keep only the 10 most recent lookups
        if len(history_cache[user_id]) > 10:
            history_cache[user_id].pop()
        
        # Create keyboard with appropriate options
        keyboard = []
        
        # Add "View All Transactions" button if there are transactions
        has_transactions = (
            "marketSummary" in data and 
            "transactions" in data["marketSummary"] and 
            data["marketSummary"]["transactions"]
        )
        transaction_count = len(data["marketSummary"]["transactions"]) if has_transactions else 0
        
        if has_transactions and transaction_count > 3:
            keyboard.append([InlineKeyboardButton(
                f"📋 View All {transaction_count} Transactions", 
                callback_data="view_all_transactions"
            )])
            
            # Add quick filters if there are enough transactions
            if transaction_count >= 10:
                # Add "Recent Transactions" button - last 6 months
                six_months_ago = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
                keyboard.append([InlineKeyboardButton(
                    "🕒 Last 6 Months Only", 
                    callback_data=f"view_all_transactions:date:{six_months_ago}"
                )])
                
                # Add "High Grade Only" button
                keyboard.append([InlineKeyboardButton(
                    "🌟 Grade 4.0+ Only", 
                    callback_data="view_all_transactions:grade:4.0"
                )])
        
        # Add price trend chart option if there are historical transactions or historical data
        has_historical_data = (
            "historicalAverages" in data and 
            (("last30days" in data["historicalAverages"] and "price" in data["historicalAverages"]["last30days"]) or
             ("lastMonth" in data["historicalAverages"] and "price" in data["historicalAverages"]["lastMonth"]) or
             ("lastSixMonths" in data["historicalAverages"] and "price" in data["historicalAverages"]["lastSixMonths"]) or
             ("lastYear" in data["historicalAverages"] and "price" in data["historicalAverages"]["lastYear"]))
        )
        
        if has_historical_data or (has_transactions and transaction_count >= 3):
            keyboard.append([InlineKeyboardButton(
                "📈 Generate Price Trend Chart", 
                callback_data=f"generate_chart:{vin}"
            )])
        
        # Add refinement option if no color or grade were provided
        if 'color' not in query_params or 'grade' not in query_params:
            keyboard.append([InlineKeyboardButton("🔄 Refine Valuation", callback_data="refine_valuation")])
        
        # Only show keyboard if there are buttons to display
        if keyboard:
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "🔍 *Additional options:*",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            
    except Exception as e:
        logger.error(f"Error fetching VIN data: {e}")
        await update.message.reply_text(
            f"⚠️ *Error fetching data for VIN:* `{vin}`\nPlease try again later.",
            parse_mode="Markdown"
        )

async def refine_valuation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the refinement button click."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id not in user_data_dict:
        await query.edit_message_text("Sorry, your session has expired. Please start a new search with /vin.")
        return ConversationHandler.END
    
    # Start with color selection
    colors = ["BLACK", "WHITE", "SILVER", "GRAY", "RED", "BLUE", "BROWN", "GREEN", "GOLD", "OTHER"]
    keyboard = []
    for color in colors:
        keyboard.append([InlineKeyboardButton(color, callback_data=f"color_{color}")])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Please select the vehicle color:", reply_markup=reply_markup)
    return CHOOSING_COLOR

async def color_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the color selection."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id not in user_data_dict:
        await query.edit_message_text("Sorry, your session has expired. Please start a new search with /vin.")
        return ConversationHandler.END
    
    # Get the color from callback data
    color = query.data.split("_")[1]
    user_data_dict[user_id]['params']['color'] = color
    
    # Now ask for grade (Manheim uses 0-5 scale)
    grades = ["1.0", "1.5", "2.0", "2.5", "3.0", "3.5", "4.0", "4.5", "5.0"]
    keyboard = []
    for grade in grades:
        keyboard.append([InlineKeyboardButton(f"Grade {grade}", callback_data=f"grade_{grade}")])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"Selected color: {color}\nPlease select the vehicle condition grade:",
        reply_markup=reply_markup
    )
    return CHOOSING_GRADE

async def grade_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the grade selection."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id not in user_data_dict:
        await query.edit_message_text("Sorry, your session has expired. Please start a new search with /vin.")
        return ConversationHandler.END
    
    # Get the grade from callback data
    grade = query.data.split("_")[1]
    user_data_dict[user_id]['params']['grade'] = float(grade)
    
    # Ask for odometer (mileage)
    keyboard = [
        [
            InlineKeyboardButton("< 10,000", callback_data="odometer_5000"),
            InlineKeyboardButton("10-30k", callback_data="odometer_20000")
        ],
        [
            InlineKeyboardButton("30-60k", callback_data="odometer_45000"),
            InlineKeyboardButton("60-100k", callback_data="odometer_80000")
        ],
        [
            InlineKeyboardButton("100-150k", callback_data="odometer_125000"),
            InlineKeyboardButton("> 150k", callback_data="odometer_175000")
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"Selected color: {user_data_dict[user_id]['params']['color']}\n"
        f"Selected grade: {grade}\n"
        f"Please select approximate mileage:",
        reply_markup=reply_markup
    )
    return CHOOSING_ODOMETER

async def odometer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the odometer selection."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id not in user_data_dict:
        await query.edit_message_text("Sorry, your session has expired. Please start a new search with /vin.")
        return ConversationHandler.END
    
    # Get the odometer from callback data
    odometer = query.data.split("_")[1]
    user_data_dict[user_id]['params']['odometer'] = int(odometer)
    
    # Ask for region
    keyboard = [
        [
            InlineKeyboardButton("Northeast (NE)", callback_data="region_NE"),
            InlineKeyboardButton("Southeast (SE)", callback_data="region_SE")
        ],
        [
            InlineKeyboardButton("Midwest (MW)", callback_data="region_MW"),
            InlineKeyboardButton("Southwest (SW)", callback_data="region_SW")
        ],
        [
            InlineKeyboardButton("West (W)", callback_data="region_W"),
            InlineKeyboardButton("Skip", callback_data="region_skip")
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"Selected color: {user_data_dict[user_id]['params']['color']}\n"
        f"Selected grade: {user_data_dict[user_id]['params']['grade']}\n"
        f"Selected mileage: {odometer}\n"
        f"Please select region:",
        reply_markup=reply_markup
    )
    return CHOOSING_REGION

async def region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the region selection and fetch refined valuation."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id not in user_data_dict:
        await query.edit_message_text("Sorry, your session has expired. Please start a new search with /vin.")
        return ConversationHandler.END
    
    # Get the region from callback data if not skipped
    region_data = query.data.split("_")[1]
    if region_data != "skip":
        user_data_dict[user_id]['params']['region'] = region_data
    
    # Show that we're processing
    await query.edit_message_text("Fetching refined valuation with your parameters...")
    
    # Get the data for the API call
    user_data = user_data_dict[user_id]
    vin = user_data['vin']
    subseries = user_data['subseries']
    transmission = user_data['transmission']
    params = user_data['params']
    
    try:
        # Get vehicle data from Manheim API with the refined parameters
        data = get_vin_valuation(vin, subseries, transmission, **params)
        
        if not data:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"No auction data found for VIN: {vin} with the specified parameters."
            )
        else:
            # Format and send the response
            message = format_auction_data(data)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"📊 Refined Valuation Results:\n\n{message}",
                parse_mode="Markdown"
            )
            
            # Add to history cache
            if user_id not in history_cache:
                history_cache[user_id] = []
                
            # Add the refined lookup to the history
            history_cache[user_id].insert(0, {
                'type': 'vin',
                'query': {
                    'vin': vin,
                    'subseries': subseries,
                    'transmission': transmission,
                    'params': params.copy()
                },
                'data': data,
                'timestamp': datetime.now(),
                'refined': True
            })
            
            # Keep only the 10 most recent lookups
            if len(history_cache[user_id]) > 10:
                history_cache[user_id].pop()
            
    except Exception as e:
        logger.error(f"Error fetching refined VIN data: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Error fetching refined data for VIN: {vin}. Please try again later."
        )
    
    # Clear user data to free memory
    if user_id in user_data_dict:
        del user_data_dict[user_id]
    
    return ConversationHandler.END

async def view_all_transactions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display all transactions for a VIN with filtering options."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id not in user_data_dict or 'data' not in user_data_dict[user_id]:
        await query.edit_message_text(
            "⚠️ *Transaction data is no longer available.*\nPlease perform a new search with /vin.",
            parse_mode="Markdown"
        )
        return
    
    # Get the full data from user storage
    data = user_data_dict[user_id]['data']
    vin = user_data_dict[user_id]['vin']
    
    # Check if transactions exist
    has_transactions = (
        "marketSummary" in data and 
        "transactions" in data["marketSummary"] and 
        data["marketSummary"]["transactions"]
    )
    
    if not has_transactions:
        await query.edit_message_text(
            "❌ *No transaction data available for this VIN.*",
            parse_mode="Markdown"
        )
        return
    
    transactions = data["marketSummary"]["transactions"]
    
    # Check for transaction filters in callback data (format: "view_all_transactions:filter_type:value")
    filter_parts = query.data.split(':')
    filter_type = filter_parts[1] if len(filter_parts) > 1 else None
    filter_value = filter_parts[2] if len(filter_parts) > 2 else None
    
    # Apply filters if provided
    filtered_transactions = transactions
    filter_description = ""
    
    if filter_type and filter_value:
        if filter_type == "grade":
            # Convert grade filter to match API format
            min_grade = float(filter_value)
            filter_description = f"(Grade ≥ {filter_value})"
            filtered_transactions = [
                tx for tx in transactions 
                if "conditionGrade" in tx and 
                (float(tx["conditionGrade"]) / 10 if float(tx["conditionGrade"]) > 5 else float(tx["conditionGrade"])) >= min_grade
            ]
        elif filter_type == "odometer":
            # Odometer filter (less than the specified value)
            max_miles = int(filter_value)
            filter_description = f"(Mileage ≤ {max_miles:,})"
            filtered_transactions = [
                tx for tx in transactions 
                if "odometer" in tx and int(tx["odometer"]) <= max_miles
            ]
        elif filter_type == "date":
            # Date filter (newer or equal to the specified date)
            date_threshold = filter_value
            filter_description = f"(Date ≥ {date_threshold})"
            filtered_transactions = [
                tx for tx in transactions 
                if "saleDate" in tx and tx["saleDate"].split('T')[0] >= date_threshold
            ]
        elif filter_type == "region":
            # Region filter (exact match)
            region = filter_value
            filter_description = f"(Region: {region})"
            filtered_transactions = [
                tx for tx in transactions 
                if "region" in tx and tx["region"] == region
            ]
    
    # Create a detailed message with all transactions
    if filter_description:
        message = f"📋 *Filtered Transactions for VIN:* `{vin}` {filter_description}\n\n"
    else:
        message = f"📋 *All Transactions for VIN:* `{vin}`\n\n"
    
    # Show count of displayed transactions vs total
    message += f"*Showing {len(filtered_transactions)} of {len(transactions)} transactions*\n\n"
    
    # Display pagination info if needed
    page = 1
    transactions_per_page = 10
    max_pages = (len(filtered_transactions) + transactions_per_page - 1) // transactions_per_page
    
    # Extract page number if in callback data (format additional part: :page:3)
    if len(filter_parts) > 3 and filter_parts[3] == "page" and len(filter_parts) > 4:
        try:
            page = int(filter_parts[4])
            if page < 1:
                page = 1
            elif page > max_pages:
                page = max_pages
        except ValueError:
            page = 1
    
    # Calculate slice for pagination
    start_idx = (page - 1) * transactions_per_page
    end_idx = min(start_idx + transactions_per_page, len(filtered_transactions))
    
    # Add pagination info if needed
    if len(filtered_transactions) > transactions_per_page:
        message += f"*Page {page} of {max_pages}*\n\n"
    
    # Add filter options if we're on the first page and not already filtering
    if page == 1 and not filter_type:
        message += "*Filter options:* Use buttons below to filter transactions\n\n"
    
    # Display transactions for current page
    for i, tx in enumerate(filtered_transactions[start_idx:end_idx], start_idx + 1):
        message += f"*Transaction #{i}*\n"
        
        if "price" in tx:
            message += f"• *Price:* ${tx.get('price', 0):,.2f}\n"
        
        if "saleDate" in tx:
            sale_date = tx.get('saleDate', '').split('T')[0]  # Format ISO date
            message += f"• *Date:* {sale_date}\n"
        
        if "odometer" in tx:
            message += f"• *Mileage:* {tx.get('odometer', 0):,} miles\n"
        
        if "conditionGrade" in tx:
            grade_value = tx.get('conditionGrade', 'N/A')
            if isinstance(grade_value, (int, float)) and grade_value > 5:
                grade_value = grade_value / 10.0
            message += f"• *Condition:* {grade_value}/5.0\n"
        
        if "location" in tx:
            message += f"• *Location:* {tx.get('location', 'N/A')}\n"
        
        if "lane" in tx:
            message += f"• *Lane:* {tx.get('lane', 'N/A')}\n"
        
        if "sellerName" in tx:
            message += f"• *Seller:* {tx.get('sellerName', 'N/A')}\n"
        
        # Add only important additional transaction details
        important_fields = ["color", "trim", "model", "bodyStyle", "cylinder", "fuel"]
        for key in important_fields:
            if key in tx and tx[key]:
                # Format the key with spaces before uppercase letters
                formatted_key = ''.join(' ' + c if c.isupper() else c for c in key).strip().capitalize()
                message += f"• *{formatted_key}:* {tx[key]}\n"
        
        message += "\n"
    
    # Create keyboard with filter options and pagination controls
    keyboard = []
    
    # Add filter buttons on first page if not already filtered
    if page == 1 and not filter_type:
        # Grade filters
        keyboard.append([
            InlineKeyboardButton("Grade ≥ 4.0", callback_data="view_all_transactions:grade:4.0"),
            InlineKeyboardButton("Grade ≥ 3.0", callback_data="view_all_transactions:grade:3.0")
        ])
        
        # Mileage filters
        keyboard.append([
            InlineKeyboardButton("Miles ≤ 50k", callback_data="view_all_transactions:odometer:50000"),
            InlineKeyboardButton("Miles ≤ 100k", callback_data="view_all_transactions:odometer:100000")
        ])
        
        # Date filters - last 6 months and last 1 year
        six_months_ago = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
        one_year_ago = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        keyboard.append([
            InlineKeyboardButton("Last 6 Months", callback_data=f"view_all_transactions:date:{six_months_ago}"),
            InlineKeyboardButton("Last Year", callback_data=f"view_all_transactions:date:{one_year_ago}")
        ])
    
    # Add pagination controls if needed
    if len(filtered_transactions) > transactions_per_page:
        pagination_buttons = []
        
        # Previous page button (if not on first page)
        if page > 1:
            cb_data = f"view_all_transactions:{filter_type or ''}:{filter_value or ''}:page:{page - 1}"
            pagination_buttons.append(InlineKeyboardButton("« Prev", callback_data=cb_data))
            
        # Page indicator
        pagination_buttons.append(InlineKeyboardButton(f"{page}/{max_pages}", callback_data="noop"))
        
        # Next page button (if not on last page)
        if page < max_pages:
            cb_data = f"view_all_transactions:{filter_type or ''}:{filter_value or ''}:page:{page + 1}"
            pagination_buttons.append(InlineKeyboardButton("Next »", callback_data=cb_data))
            
        keyboard.append(pagination_buttons)
    
    # Add reset filters button if currently filtering
    if filter_type:
        keyboard.append([InlineKeyboardButton("❌ Clear Filters", callback_data="view_all_transactions")])
    
    # Add a cancel button at the bottom
    keyboard.append([InlineKeyboardButton("Close", callback_data="cancel")])
    
    # Set up reply markup
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Split message if it's too long
    MAX_MESSAGE_LENGTH = 4096  # Telegram's limit
    
    if len(message) <= MAX_MESSAGE_LENGTH:
        await query.edit_message_text(message, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        # Send initial message
        await query.edit_message_text("Sending transaction details...")
        
        # Split into multiple messages
        for i in range(0, len(message), MAX_MESSAGE_LENGTH):
            chunk = message[i:i + MAX_MESSAGE_LENGTH]
            
            # Only add keyboard to the last chunk
            if i + MAX_MESSAGE_LENGTH >= len(message):
                await context.bot.send_message(
                    chat_id=update.effective_chat.id, 
                    text=chunk,
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )
            else:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id, 
                    text=chunk,
                    parse_mode="Markdown"
                )

async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the refinement process."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id in user_data_dict:
        del user_data_dict[user_id]
    
    await query.edit_message_text(
        "❌ *Refinement canceled*\nYou can start a new search with /vin.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END
    
async def page_navigation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle pagination navigation for large result sets."""
    query = update.callback_query
    await query.answer()
    
    # Extract page navigation data
    # Format: page:vin:page_number or page:year:make:model:page_number
    parts = query.data.split(':')
    
    if len(parts) < 3:
        await query.edit_message_text("❌ Invalid pagination format", parse_mode="Markdown")
        return
    
    # Check if it's a VIN or YMM navigation
    page_number = int(parts[-1])
    
    # For VIN pagination
    if len(parts) == 3:
        vin = parts[1]
        
        # Try to find the data in user history
        user_id = update.effective_user.id
        vehicle_data = None
        
        if user_id in history_cache:
            # Look for matching VIN in history
            for entry in history_cache[user_id]:
                if entry['type'] == 'vin' and entry['query']['vin'] == vin:
                    vehicle_data = entry['data']
                    break
        
        # If not found in history but user has active data
        if not vehicle_data and user_id in user_data_dict and user_data_dict[user_id].get('vin') == vin:
            vehicle_data = user_data_dict[user_id].get('data')
        
        if not vehicle_data:
            await query.edit_message_text(
                "❌ *Data no longer available*\nPlease perform a new search.",
                parse_mode="Markdown"
            )
            return
            
        # Format the data for the requested page
        MAX_MESSAGE_LENGTH = 4000
        page_data = format_auction_data(vehicle_data, MAX_MESSAGE_LENGTH, page_number)
        
        # Create pagination controls
        keyboard = []
        pagination_row = []
        
        if page_number > 1:
            pagination_row.append(InlineKeyboardButton("« Prev", callback_data=f"page:{vin}:{page_number-1}"))
        
        pagination_row.append(InlineKeyboardButton(f"{page_number}/{page_data['total_pages']}", callback_data="noop"))
        
        if page_number < page_data['total_pages']:
            pagination_row.append(InlineKeyboardButton("Next »", callback_data=f"page:{vin}:{page_number+1}"))
        
        keyboard.append(pagination_row)
        
        # Add options to view all transactions if available
        if "marketSummary" in vehicle_data and "transactions" in vehicle_data["marketSummary"]:
            transactions = vehicle_data["marketSummary"]["transactions"]
            if len(transactions) > 3:
                keyboard.append([InlineKeyboardButton(
                    f"📋 View All {len(transactions)} Transactions", 
                    callback_data="view_all_transactions"
                )])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Update the message with the new page
        await query.edit_message_text(
            page_data['message'],
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    
    # For YMM pagination (not implemented yet, placeholder)
    elif len(parts) == 5:
        year = parts[1]
        make = parts[2]
        model = parts[3]
        
        # Similar implementation as above, but for YMM data
        await query.edit_message_text(
            f"YMM pagination not yet implemented. Page {page_number} for {year} {make} {model}",
            parse_mode="Markdown"
        )
        
async def generate_chart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate and send a price trend chart for a vehicle."""
    query = update.callback_query
    await query.answer()
    
    # Extract VIN or YMM data from callback
    parts = query.data.split(':')
    if len(parts) < 2:
        await query.edit_message_text("❌ Invalid chart request format", parse_mode="Markdown")
        return
    
    chart_type = parts[0]  # "generate_chart"
    identifier = parts[1]  # VIN or other identifier
    
    # Status message while generating chart
    await query.edit_message_text("📊 *Generating price trend chart...*", parse_mode="Markdown")
    
    user_id = update.effective_user.id
    vehicle_data = None
    vehicle_info = ""
    
    # Find the vehicle data from user history or active context
    if user_id in history_cache:
        # Look for matching VIN in history
        for entry in history_cache[user_id]:
            if entry['type'] == 'vin' and entry['query']['vin'] == identifier:
                vehicle_data = entry['data']
                # Get basic vehicle info
                if 'vehicle' in vehicle_data:
                    v = vehicle_data['vehicle']
                    if all(k in v for k in ['year', 'make', 'model']):
                        vehicle_info = f"{v.get('year')} {v.get('make')} {v.get('model')}"
                break
    
    # If not found in history but user has active data
    if not vehicle_data and user_id in user_data_dict and user_data_dict[user_id].get('vin') == identifier:
        vehicle_data = user_data_dict[user_id].get('data')
        # Get basic vehicle info
        if 'vehicle' in vehicle_data:
            v = vehicle_data['vehicle']
            if all(k in v for k in ['year', 'make', 'model']):
                vehicle_info = f"{v.get('year')} {v.get('make')} {v.get('model')}"
    
    if not vehicle_data:
        await query.edit_message_text(
            "❌ *Data no longer available*\nPlease perform a new search to generate a chart.",
            parse_mode="Markdown"
        )
        return
    
    # Generate chart image
    chart_image = generate_price_trend_chart(vehicle_data, vehicle_info)
    
    if not chart_image:
        await query.edit_message_text(
            "❌ *Unable to generate chart*\nNot enough price data available.",
            parse_mode="Markdown"
        )
        return
    
    # Send the chart image
    await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=chart_image,
        caption=f"📈 *Price Trend Chart*\n{vehicle_info} (VIN: {identifier})",
        parse_mode="Markdown"
    )
    
    # Revert original message to indicate chart was sent
    original_message = "📊 *Price trend chart generated!*"
    await query.edit_message_text(original_message, parse_mode="Markdown")
    
def generate_price_trend_chart(data, vehicle_info="Vehicle"):
    """
    Generate a price trend chart image from vehicle data.
    
    Args:
        data (dict): The vehicle data response from Manheim API
        vehicle_info (str): Vehicle information for chart title
        
    Returns:
        BytesIO: Image data as bytes I/O stream or None if not enough data
    """
    # Prepare data collections for chart
    time_points = []
    prices = []
    price_labels = []
    mileage_data = []
    chart_title = f"Price Trend for {vehicle_info}"
    
    # Historical averages from API
    if "historicalAverages" in data:
        history = data["historicalAverages"]
        
        # Order periods from oldest to newest to chart correctly
        periods = [
            ("lastYear", "1 Year Ago"),
            ("lastSixMonths", "6 Months Ago"),
            ("lastMonth", "1 Month Ago"),
            ("last30days", "Last 30 Days")
        ]
        
        for period_key, period_label in periods:
            if period_key in history and "price" in history[period_key]:
                time_points.append(period_label)
                price = history[period_key]["price"]
                prices.append(price)
                price_labels.append(f"${price:,.0f}")
                
                if "odometer" in history[period_key]:
                    mileage_data.append(history[period_key]["odometer"])
                else:
                    mileage_data.append(None)
    
    # Add transaction data points if available
    if "marketSummary" in data and "transactions" in data["marketSummary"]:
        transactions = data["marketSummary"]["transactions"]
        
        # Only use transaction data if we have dates and prices
        valid_transactions = [
            tx for tx in transactions 
            if "saleDate" in tx and "price" in tx
        ]
        
        # Sort transactions by date (oldest to newest)
        valid_transactions.sort(key=lambda tx: tx["saleDate"])
        
        # Only add up to 10 additional transaction points to keep chart readable
        max_tx_points = 10
        if len(valid_transactions) > max_tx_points:
            # Intelligently sample the transactions to show trend
            step = len(valid_transactions) // max_tx_points
            valid_transactions = valid_transactions[::step][:max_tx_points]
        
        # Add transaction points to the chart
        for tx in valid_transactions:
            # Format the date to short form
            date_str = tx["saleDate"].split("T")[0]
            try:
                date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                date_label = date_obj.strftime("%m/%d/%y")
            except ValueError:
                date_label = date_str
                
            time_points.append(date_label)
            price = tx["price"]
            prices.append(price)
            price_labels.append(f"${price:,.0f}")
            
            if "odometer" in tx:
                mileage_data.append(tx["odometer"])
            else:
                mileage_data.append(None)
    
    # Ensure we have at least 2 data points for a meaningful chart
    if len(time_points) < 2:
        return None
    
    # Create the chart
    plt.figure(figsize=(10, 6))
    
    # Set style
    plt.style.use('ggplot')
    
    # Plot price trend line
    ax1 = plt.gca()
    line1, = ax1.plot(time_points, prices, marker='o', linewidth=2, color='#3366cc', markersize=8)
    
    # Add price labels above each point
    for i, price in enumerate(prices):
        ax1.annotate(price_labels[i], 
                    (time_points[i], prices[i]), 
                    textcoords="offset points", 
                    xytext=(0, 10), 
                    ha='center',
                    fontweight='bold')
    
    # Set up y-axis for prices
    ax1.set_ylabel('Price (USD)', fontsize=12, fontweight='bold')
    
    # Add mileage information on secondary axis if available
    has_mileage = any(m is not None for m in mileage_data)
    if has_mileage:
        ax2 = ax1.twinx()
        # Filter out None values
        valid_indices = [i for i, m in enumerate(mileage_data) if m is not None]
        valid_timepoints = [time_points[i] for i in valid_indices]
        valid_mileage = [mileage_data[i] for i in valid_indices]
        
        if valid_mileage:
            line2, = ax2.plot(valid_timepoints, valid_mileage, marker='s', linestyle='--', 
                             color='#ff9900', linewidth=1.5, markersize=6)
            ax2.set_ylabel('Mileage', fontsize=12, fontweight='bold')
            
            # Add legend
            if len(valid_mileage) > 1:
                plt.legend([line1, line2], ['Price', 'Mileage'], loc='upper center', 
                          bbox_to_anchor=(0.5, -0.15), ncol=2)
            else:
                plt.legend([line1], ['Price'], loc='upper center', 
                          bbox_to_anchor=(0.5, -0.1))
    else:
        plt.legend([line1], ['Price'], loc='upper center', bbox_to_anchor=(0.5, -0.1))
    
    # Add forecasted price if available
    if "forecast" in data:
        forecast_points = []
        forecast_prices = []
        forecast_labels = []
        
        if "nextMonth" in data["forecast"] and "wholesale" in data["forecast"]["nextMonth"]:
            forecast_points.append("Next Month")
            forecast_prices.append(data["forecast"]["nextMonth"]["wholesale"])
            forecast_labels.append(f"${data['forecast']['nextMonth']['wholesale']:,.0f}")
        
        if "nextYear" in data["forecast"] and "wholesale" in data["forecast"]["nextYear"]:
            forecast_points.append("Next Year")
            forecast_prices.append(data["forecast"]["nextYear"]["wholesale"])
            forecast_labels.append(f"${data['forecast']['nextYear']['wholesale']:,.0f}")
        
        if forecast_points:
            # Extend x-axis with forecast points
            all_timepoints = time_points + forecast_points
            all_prices = prices + forecast_prices
            
            # Plot forecast as a dotted line
            ax1.plot(forecast_points, forecast_prices, marker='o', linestyle='dotted', 
                    color='green', linewidth=2, markersize=8)
            
            # Add forecast labels
            for i, price in enumerate(forecast_prices):
                ax1.annotate(forecast_labels[i], 
                           (forecast_points[i], forecast_prices[i]), 
                           textcoords="offset points", 
                           xytext=(0, 10), 
                           ha='center', 
                           fontweight='bold', 
                           color='green')
            
            # Add "Forecast" notation
            plt.figtext(0.7, 0.01, "Green points show forecasted values", 
                       fontsize=9, style='italic', ha='center')
    
    # Set up chart title and layout
    plt.title(chart_title, fontsize=14, fontweight='bold', pad=15)
    plt.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.tight_layout()
    
    # Save chart to bytes buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=100)
    buf.seek(0)
    
    # Close the figure to free memory
    plt.close()
    
    return buf

def validate_ymm(year, make, model):
    """
    Validate Year/Make/Model parameters
    
    Args:
        year (str): Vehicle year
        make (str): Vehicle manufacturer
        model (str): Vehicle model
        
    Returns:
        tuple: (bool, str) whether valid and error message if not
    """
    # Validate year
    try:
        year_int = int(year)
        current_year = datetime.now().year
        
        # First cars were made in late 1800s, and we don't want future years
        if year_int < 1885 or year_int > current_year + 1:
            return False, f"Year must be between 1885 and {current_year + 1}"
    except ValueError:
        return False, "Year must be a number"
    
    # Validate make and model (basic validation - must be non-empty)
    if not make or len(make) < 2:
        return False, "Make must be at least 2 characters"
    
    if not model or len(model) < 2:
        return False, "Model must be at least 2 characters"
    
    return True, ""

def get_ymm_valuation(year, make, model, trim=None, **query_params):
    """
    Get valuation data for Year/Make/Model from Manheim API.
    
    Args:
        year (str): Vehicle year
        make (str): Vehicle manufacturer
        model (str): Vehicle model
        trim (str, optional): Vehicle trim
        **query_params: Additional query parameters such as:
            - date (str): Date for historical valuation (YYYY-MM-DD format)
    """
    # Validate YMM parameters
    is_valid, error_msg = validate_ymm(year, make, model)
    if not is_valid:
        logger.error(f"Invalid YMM parameters: {error_msg} - {year}/{make}/{model}")
        return None
        
    # Validate date parameter
    if "date" in query_params:
        date_str = query_params["date"]
        try:
            # Check if date is in correct format
            datetime.strptime(date_str, "%Y-%m-%d")
            
            # Check if date is after minimum allowed date (2018-10-08)
            min_date = datetime.strptime("2018-10-08", "%Y-%m-%d")
            requested_date = datetime.strptime(date_str, "%Y-%m-%d")
            
            if requested_date < min_date:
                logger.warning(f"Date too early: {date_str}. Must be on or after 2018-10-08")
                query_params["date"] = None
                
            # Check if date is in the future
            today = datetime.now()
            if requested_date > today:
                logger.warning(f"Future date: {date_str}. Must be on or before today's date")
                query_params["date"] = None
                
        except ValueError:
            logger.warning(f"Invalid date format: {date_str}. Must be in YYYY-MM-DD format")
            query_params["date"] = None
    
    # Get authentication token
    token = get_manheim_token()
    if not token:
        logger.error("Failed to get authentication token")
        return None
    
    # URL parameters are part of the path
    # URL encode parameters for safety
    from urllib.parse import quote
    year_enc = quote(str(year))
    make_enc = quote(str(make))
    model_enc = quote(str(model))
    
    url = MANHEIM_YMM_URL.format(year=year_enc, make=make_enc, model=model_enc)
    
    # Query parameters
    params = {}
    if trim:
        params["trim"] = trim
        
    # Add additional query parameters
    for key, value in query_params.items():
        if value is not None:
            params[key] = value
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }
    
    try:
        logger.info(f"Fetching valuation data for YMM: {year}/{make}/{model}")
        response = requests.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        
        data = response.json()
        
        # Validate response data
        if not data:
            logger.warning(f"Empty response for YMM: {year}/{make}/{model}")
            return None
            
        # Check if the response has the expected structure
        if "vehicle" not in data:
            logger.warning(f"Unexpected API response format for YMM: {year}/{make}/{model} - missing vehicle data")
        
        logger.info(f"Successfully retrieved valuation data for YMM: {year}/{make}/{model}")
        return data
        
    except requests.exceptions.Timeout:
        logger.error(f"Timeout while fetching data for YMM: {year}/{make}/{model}")
        return None
    except requests.exceptions.ConnectionError:
        logger.error(f"Connection error while fetching data for YMM: {year}/{make}/{model}")
        return None
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logger.warning(f"No data found for YMM: {year}/{make}/{model}")
            return None
        logger.error(f"HTTP error fetching YMM data: {e.response.status_code} - {e.response.text}")
        return None
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON response for YMM: {year}/{make}/{model}")
        return None
    except Exception as e:
        logger.error(f"Error fetching YMM data: {e}")
        return None

async def ymm_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get auction data for a Year/Make/Model."""
    if len(context.args) < 3:
        await update.message.reply_text(
            "❓ *Please provide Year, Make, and Model*\n\n"
            "*Examples:*\n"
            "• `/ymm 2020 Honda Accord`\n"
            "• `/ymm 2020 Honda Accord date=2023-05-15`",
            parse_mode="Markdown"
        )
        return

    # Extract basic YMM parameters first
    basic_args = []
    keyword_args = {}
    
    for arg in context.args:
        if '=' in arg:
            key, value = arg.split('=', 1)
            keyword_args[key.lower()] = value
        else:
            basic_args.append(arg)
    
    # We need at least 3 basic args for year, make, model
    if len(basic_args) < 3:
        await update.message.reply_text(
            "❓ *Missing required parameters*\n\n"
            "Year, Make, and Model are required.\n"
            "*Example:* `/ymm 2020 Honda Accord`",
            parse_mode="Markdown"
        )
        return
    
    year = basic_args[0]
    make = basic_args[1]
    model = " ".join(basic_args[2:])
    
    # Validate YMM parameters before proceeding
    is_valid, error_msg = validate_ymm(year, make, model)
    if not is_valid:
        await update.message.reply_text(
            f"❌ *Invalid parameters*: {error_msg}\n\n"
            f"You entered: Year: `{year}`, Make: `{make}`, Model: `{model}`\n\n"
            "Please provide valid values.",
            parse_mode="Markdown"
        )
        return
    
    # Validate and process keyword arguments
    query_params = {}
    
    # Process date parameter if present
    if 'date' in keyword_args:
        date_value = keyword_args['date']
        try:
            # Parse date to validate format
            requested_date = datetime.strptime(date_value, "%Y-%m-%d")
            
            # Check if date is after minimum allowed date (2018-10-08)
            min_date = datetime.strptime("2018-10-08", "%Y-%m-%d")
            if requested_date < min_date:
                await update.message.reply_text(
                    f"⚠️ *Warning*: Date must be on or after 2018-10-08. Using current date.",
                    parse_mode="Markdown"
                )
            # Check if date is in the future
            elif requested_date > datetime.now():
                await update.message.reply_text(
                    f"⚠️ *Warning*: Date cannot be in the future. Using current date.",
                    parse_mode="Markdown"
                )
            else:
                query_params['date'] = date_value
                
        except ValueError:
            await update.message.reply_text(
                f"⚠️ *Warning*: Invalid date format '{date_value}'. Must be in YYYY-MM-DD format. Using current date.",
                parse_mode="Markdown"
            )
    
    # Construct search message
    search_message = f"🔍 *Searching for:* `{year} {make} {model}`"
    if 'date' in query_params:
        search_message += f"\n*Date:* {query_params['date']}"
    
    await update.message.reply_text(
        search_message + "...",
        parse_mode="Markdown"
    )
    
    try:
        # Get vehicle data from Manheim API
        data = get_ymm_valuation(year, make, model, **query_params)
        
        if not data:
            await update.message.reply_text(
                f"❌ *No auction data found for {year} {make} {model}*",
                parse_mode="Markdown"
            )
            return
            
        # Format and send the response
        message = format_auction_data(data)
        await update.message.reply_text(message, parse_mode="Markdown")
        
        # Add to history cache
        user_id = update.effective_user.id
        if user_id not in history_cache:
            history_cache[user_id] = []
            
        # Add the new lookup to the start of the list (most recent first)
        history_entry = {
            'type': 'ymm',
            'query': {
                'year': year,
                'make': make,
                'model': model
            },
            'data': data,
            'timestamp': datetime.now()
        }
        
        # Add date to query if used
        if 'date' in query_params:
            history_entry['query']['date'] = query_params['date']
            
        history_cache[user_id].insert(0, history_entry)
        
        # Keep only the 10 most recent lookups
        if len(history_cache[user_id]) > 10:
            history_cache[user_id].pop()
        
    except Exception as e:
        logger.error(f"Error fetching YMM data: {e}")
        await update.message.reply_text(
            f"⚠️ *Error fetching data for {year} {make} {model}*\nPlease try again later.",
            parse_mode="Markdown"
        )

def format_auction_data(data, max_length=None, page=1):
    """
    Format the auction data into a readable message based on Manheim Valuations API structure.
    
    Args:
        data (dict): The API response data to format
        max_length (int, optional): Maximum message length to return (for pagination)
        page (int, optional): Page number for paginated results
        
    Returns:
        dict: Dictionary containing message parts and pagination info
    """
    if not isinstance(data, dict):
        return {"message": f"🚗 *Vehicle Auction Data*\n\n{str(data)}", "has_more": False, "total_pages": 1}
    
    # Main message content
    message = []
    message.append("🚗 *Vehicle Auction Data*\n\n")
    
    # Create different sections that can be paginated
    sections = []
    
    # Section 1: Basic vehicle and valuation info
    section1 = ""
    
    # Add valuation date if present
    if "requestedDate" in data:
        section1 += f"📅 *Valuation Date:* {data['requestedDate']}\n\n"
    
    # Vehicle information
    if "vehicle" in data:
        vehicle = data["vehicle"]
        section1 += "📋 *Vehicle Info*\n"
        if "year" in vehicle and "make" in vehicle and "model" in vehicle:
            section1 += f"• *{vehicle.get('year')} {vehicle.get('make')} {vehicle.get('model')}"
            if "trim" in vehicle:
                section1 += f" {vehicle.get('trim')}"
            section1 += "*\n"
        if "vin" in vehicle:
            section1 += f"• VIN: `{vehicle.get('vin')}`\n"
        if "style" in vehicle:
            section1 += f"• Style: {vehicle.get('style')}\n"
        if "engineSize" in vehicle:
            section1 += f"• Engine: {vehicle.get('engineSize')}\n"
        if "transmission" in vehicle:
            section1 += f"• Transmission: {vehicle.get('transmission')}\n"
        if "drivetrain" in vehicle:
            section1 += f"• Drivetrain: {vehicle.get('drivetrain')}\n"
        if "subSeries" in vehicle:
            section1 += f"• SubSeries: {vehicle.get('subSeries')}\n"
        section1 += "\n"
    
    # Current wholesale and retail values
    if "adjustedPricing" in data:
        pricing = data["adjustedPricing"]
        section1 += "💰 *Current Valuation*\n"
        
        # Wholesale values
        if "wholesale" in pricing:
            wholesale = pricing["wholesale"]
            section1 += f"• *Wholesale Value:* ${wholesale.get('average', 0):,.2f}\n"
            section1 += f"  Range: ${wholesale.get('below', 0):,.2f} - ${wholesale.get('above', 0):,.2f}\n"
        
        # Retail values
        if "retail" in pricing:
            retail = pricing["retail"]
            section1 += f"• *Retail Value:* ${retail.get('average', 0):,.2f}\n"
            section1 += f"  Range: ${retail.get('below', 0):,.2f} - ${retail.get('above', 0):,.2f}\n"
            
        # Adjustment factors
        if "adjustedBy" in pricing:
            adjustments = pricing["adjustedBy"]
            if adjustments and any(adjustments.values()):
                section1 += "• *Adjusted For:* "
                factors = []
                
                if "Color" in adjustments:
                    factors.append(f"Color: {adjustments['Color']}")
                if "Grade" in adjustments:
                    grade_value = adjustments['Grade']
                    # Convert grade from integer format (50) to decimal format (5.0)
                    try:
                        grade_decimal = float(grade_value) / 10.0
                        factors.append(f"Grade: {grade_decimal:.1f}")
                    except (ValueError, TypeError):
                        factors.append(f"Grade: {grade_value}")
                if "Odometer" in adjustments:
                    factors.append(f"Mileage: {int(adjustments['Odometer']):,}")
                if "Region" in adjustments and adjustments["Region"] != "NA":
                    factors.append(f"Region: {adjustments['Region']}")
                    
                section1 += ", ".join(factors) + "\n"
        
        section1 += "\n"
    
    sections.append(section1)
    
    # Section 2: Historical trends and forecasts
    section2 = ""
    
    # Historical trends
    if "historicalAverages" in data:
        history = data["historicalAverages"]
        section2 += "📈 *Historical Price Trends*\n"
        
        trend_data = []
        
        if "last30days" in history and "price" in history["last30days"]:
            trend_data.append({
                "period": "Last 30 Days",
                "price": history["last30days"].get("price", 0),
                "odometer": history["last30days"].get("odometer", 0)
            })
            
        if "lastMonth" in history and "price" in history["lastMonth"]:
            trend_data.append({
                "period": "Last Month",
                "price": history["lastMonth"].get("price", 0),
                "odometer": history["lastMonth"].get("odometer", 0)
            })
            
        if "lastSixMonths" in history and "price" in history["lastSixMonths"]:
            trend_data.append({
                "period": "Last 6 Months",
                "price": history["lastSixMonths"].get("price", 0),
                "odometer": history["lastSixMonths"].get("odometer", 0)
            })
            
        if "lastYear" in history and "price" in history["lastYear"]:
            trend_data.append({
                "period": "Last Year",
                "price": history["lastYear"].get("price", 0),
                "odometer": history["lastYear"].get("odometer", 0)
            })
            
        # Show historical data
        for item in trend_data:
            section2 += f"• *{item['period']}:* ${item['price']:,.2f}"
            if item['odometer']:
                section2 += f" @ {item['odometer']:,} miles\n"
            else:
                section2 += "\n"
                
        section2 += "\n"
    
    # Forecast data
    if "forecast" in data:
        forecast = data["forecast"]
        section2 += "🔮 *Price Forecast*\n"
        
        if "nextMonth" in forecast:
            section2 += "• *Next Month:*\n"
            if "wholesale" in forecast["nextMonth"]:
                section2 += f"  Wholesale: ${forecast['nextMonth']['wholesale']:,.2f}\n"
            if "retail" in forecast["nextMonth"]:
                section2 += f"  Retail: ${forecast['nextMonth']['retail']:,.2f}\n"
                
        if "nextYear" in forecast:
            section2 += "• *Next Year:*\n"
            if "wholesale" in forecast["nextYear"]:
                section2 += f"  Wholesale: ${forecast['nextYear']['wholesale']:,.2f}\n"
            if "retail" in forecast["nextYear"]:
                section2 += f"  Retail: ${forecast['nextYear']['retail']:,.2f}\n"
                
        section2 += "\n"
    
    sections.append(section2)
    
    # Section 3: Summary statistics
    section3 = ""
    
    # Sample size and accuracy indicators
    if "sampleSize" in data:
        section3 += f"• *Sample Size:* {data['sampleSize']} transactions\n"
    if "extendedCoverage" in data and data["extendedCoverage"]:
        section3 += "• Note: Uses Small Sample Size\n"
    if "bestMatch" in data and data["bestMatch"]:
        section3 += "• *Best Match* found for this VIN\n\n"
    
    # Market statistics
    if "marketSummary" in data and "statistics" in data["marketSummary"]:
        stats = data["marketSummary"]["statistics"]
        section3 += "📊 *Market Summary*\n"
        
        if "averagePrice" in stats:
            section3 += f"• *Avg Price:* ${stats.get('averagePrice', 0):,.2f}\n"
        if "averageOdometer" in stats:
            section3 += f"• *Avg Mileage:* {stats.get('averageOdometer', 0):,} miles\n"
        if "averageConditionGrade" in stats:
            grade_value = stats.get('averageConditionGrade', 0)
            if grade_value > 5:  # Convert from integer format (50 = 5.0)
                grade_value = grade_value / 10.0
            section3 += f"• *Avg Condition:* {grade_value:.1f}/5.0\n"
        if "transactionCount" in stats:
            section3 += f"• *Total Transactions:* {stats.get('transactionCount', 0)}\n\n"
    
    sections.append(section3)
    
    # Section 4: Recent transactions
    section4 = ""
    
    # Recent auction transactions
    if "marketSummary" in data and "transactions" in data["marketSummary"]:
        transactions = data["marketSummary"]["transactions"]
        if transactions:
            # Store transactions for potential detailed view
            data["transaction_count"] = len(transactions)
            
            section4 += f"🔄 *Recent Transactions* ({len(transactions)} total)\n"
            for i, tx in enumerate(transactions[:3], 1):  # Show only 3 in the summary view
                sale_info = []
                
                if "price" in tx:
                    sale_info.append(f"${tx.get('price', 0):,.2f}")
                
                if "saleDate" in tx:
                    sale_date = tx.get('saleDate', '').split('T')[0]  # Format ISO date
                    sale_info.append(f"{sale_date}")
                
                section4 += f"*{i}.* {' on '.join(sale_info)}\n"
                
                details = []
                if "odometer" in tx:
                    details.append(f"{tx.get('odometer', 0):,} miles")
                if "conditionGrade" in tx:
                    grade_value = tx.get('conditionGrade', 'N/A')
                    if isinstance(grade_value, (int, float)):
                        # Handle case where grade is already a decimal or needs conversion from integer (50 = 5.0)
                        if grade_value > 5:  # Likely the 50 = 5.0 format
                            grade_value = grade_value / 10.0
                        details.append(f"Grade: {grade_value:.1f}/5.0")
                    else:
                        details.append(f"Grade: {grade_value}/5.0")
                if "location" in tx:
                    details.append(f"{tx.get('location', 'N/A')}")
                
                if details:
                    section4 += f"   _({' | '.join(details)})_\n"
                
            section4 += "\n"
            
            # Add note about viewing all transactions if there are more than shown
            if len(transactions) > 3:
                section4 += f"_...and {len(transactions) - 3} more transactions. Use the button below to view all._\n\n"
    
    sections.append(section4)
    
    # Handle pagination if requested
    if max_length is not None:
        total_length = sum(len(s) for s in sections)
        total_pages = (total_length + max_length - 1) // max_length
        
        if page < 1:
            page = 1
        elif page > total_pages:
            page = total_pages
        
        # If we need pagination, build message differently
        if total_pages > 1:
            # Add pagination header
            current_message = f"🚗 *Vehicle Auction Data* (Page {page}/{total_pages})\n\n"
            
            # Calculate which sections to include based on page
            remaining_length = max_length - len(current_message)
            message_parts = []
            
            if page == 1:
                # First page always includes basic info
                for section in sections:
                    if len(current_message) + len(section) <= max_length:
                        current_message += section
                    else:
                        break
            else:
                # For other pages, need to skip content that would be on earlier pages
                cumulative_length = len(f"🚗 *Vehicle Auction Data* (Page 1/{total_pages})\n\n")
                
                for section in sections:
                    section_length = len(section)
                    
                    # If adding this section would put us on a page before the requested page,
                    # skip to the next section
                    if cumulative_length + section_length <= (page - 1) * max_length:
                        cumulative_length += section_length
                        continue
                    
                    # If this section spans the current page
                    start_offset = max(0, (page - 1) * max_length - cumulative_length)
                    end_offset = min(section_length, page * max_length - cumulative_length)
                    
                    if start_offset < end_offset:
                        # Extract the portion of this section that belongs on this page
                        section_part = section[start_offset:end_offset]
                        current_message += section_part
                    
                    cumulative_length += section_length
                    
                    # If we've filled this page, stop
                    if cumulative_length >= page * max_length:
                        break
            
            return {
                "message": current_message, 
                "has_more": page < total_pages, 
                "total_pages": total_pages,
                "current_page": page
            }
        
    # If no pagination or just one page, combine all sections
    full_message = "".join(message) + "".join(sections)
    
    return {
        "message": full_message, 
        "has_more": False, 
        "total_pages": 1,
        "current_page": 1
    }

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display user's search history."""
    user_id = update.effective_user.id
    
    # Check if user has any history
    if user_id not in history_cache or not history_cache[user_id]:
        await update.message.reply_text(
            "📭 *No search history found*\n\n"
            "Try searching for a VIN or Year/Make/Model first.",
            parse_mode="Markdown"
        )
        return
        
    # Check for filter argument (VIN or YMM)
    filter_type = None
    if context.args:
        filter_arg = context.args[0].upper()
        if filter_arg in ["VIN", "YMM"]:
            filter_type = filter_arg.lower()
    
    # Filter history based on argument if provided
    history = history_cache[user_id]
    if filter_type:
        history = [item for item in history if item['type'] == filter_type]
        
        if not history:
            await update.message.reply_text(
                f"📭 *No {filter_type.upper()} lookups found in your history*",
                parse_mode="Markdown"
            )
            return
    
    # Create history message
    message = "📋 *Your Search History*\n\n"
    
    for i, item in enumerate(history, 1):
        lookup_type = item['type'].upper()
        timestamp = item['timestamp'].strftime("%Y-%m-%d %H:%M")
        
        if lookup_type == "VIN":
            vin = item['query']['vin']
            refined = item.get('refined', False)
            historical = item.get('historical', False)
            
            # Get vehicle info from data if available
            vehicle_info = ""
            if 'data' in item and 'vehicle' in item['data']:
                vehicle = item['data']['vehicle']
                if all(k in vehicle for k in ['year', 'make', 'model']):
                    vehicle_info = f" - {vehicle.get('year')} {vehicle.get('make')} {vehicle.get('model')}"
            
            # Add indicators for special searches
            indicators = []
            if historical and 'date' in item['query']['params']:
                date_value = item['query']['params']['date']
                indicators.append(f"📅 {date_value}")
            if refined:
                indicators.append("🔄 Refined")
                
            indicator_text = f" ({', '.join(indicators)})" if indicators else ""
            
            message += f"*{i}.* {lookup_type}: `{vin}`{vehicle_info}{indicator_text}\n"
            
            # Add parameters if any
            params = []
            if item['query']['subseries']:
                params.append(f"Subseries: {item['query']['subseries']}")
            if item['query']['transmission']:
                params.append(f"Transmission: {item['query']['transmission']}")
                
            for key, value in item['query']['params'].items():
                # Skip date as it's already shown in the indicators
                if key != 'date':
                    params.append(f"{key.capitalize()}: {value}")
                
            if params:
                message += f"   _Parameters: {', '.join(params)}_\n"
                
        elif lookup_type == "YMM":
            year = item['query']['year']
            make = item['query']['make']
            model = item['query']['model']
            
            # Add date indicator if historical lookup
            date_indicator = ""
            if 'date' in item['query']:
                date_indicator = f" (📅 {item['query']['date']})"
                
            message += f"*{i}.* {lookup_type}: {year} {make} {model}{date_indicator}\n"
            
        message += f"   _({timestamp})_\n\n"
    
    # Add usage note
    message += "💡 *To reuse a previous search:*\n"
    message += "• For VIN: Use `/vin [VIN]`\n"
    message += "• For YMM: Use `/ymm [Year] [Make] [Model]`\n"
    
    # Send history message
    await update.message.reply_text(message, parse_mode="Markdown")

def main() -> None:
    """Start the bot."""
    # Check if the Telegram token is configured
    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        logger.error("TELEGRAM_BOT_TOKEN environment variable is not set. Please configure it in your .env file.")
        print("Error: Telegram bot token not configured. Please check your .env file.")
        return
        
    # Create the Application and pass it your bot's token
    try:
        application = ApplicationBuilder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    except Exception as e:
        logger.error(f"Failed to create Telegram bot: {e}")
        print(f"Error: Could not initialize the Telegram bot: {e}")
        return

    # Add conversation handler for the interactive refinement process
    refinement_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(refine_valuation_callback, pattern="^refine_valuation$")],
        states={
            CHOOSING_COLOR: [CallbackQueryHandler(color_callback, pattern="^color_")],
            CHOOSING_GRADE: [CallbackQueryHandler(grade_callback, pattern="^grade_")],
            CHOOSING_ODOMETER: [CallbackQueryHandler(odometer_callback, pattern="^odometer_")],
            CHOOSING_REGION: [CallbackQueryHandler(region_callback, pattern="^region_")],
        },
        fallbacks=[CallbackQueryHandler(cancel_callback, pattern="^cancel$")],
    )

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("vin", vin_command))
    application.add_handler(CommandHandler("ymm", ymm_command))
    application.add_handler(CommandHandler("history", history_command))
    
    # Add callback handlers
    application.add_handler(CallbackQueryHandler(view_all_transactions_callback, pattern="^view_all_transactions"))
    application.add_handler(CallbackQueryHandler(page_navigation_callback, pattern="^page:"))
    application.add_handler(CallbackQueryHandler(generate_chart_callback, pattern="^generate_chart:"))
    application.add_handler(refinement_conv_handler)

    try:
        # Start the Bot
        logger.info("Starting Manheim Telegram Bot")
        print("Starting Manheim Telegram Bot...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"Error while running the bot: {e}")
        print(f"Error: Bot crashed: {e}")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        print("\nBot stopped by user. Goodbye!")
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}", exc_info=True)
        print(f"\nCritical error: {e}")
        print("Check logs for more details.")