import os
import logging
import requests
import json
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
        "• `/ymm [Year] [Make] [Model]` - Get data by Year/Make/Model\n\n"
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
        "• Advanced: `/vin WBA3C1C5XFP853102 color=WHITE grade=3.5 odometer=20000 region=NE`\n\n"
        
        "*Parameter Options:*\n"
        "• `color` - WHITE, BLACK, SILVER, etc.\n"
        "• `grade` - 1.0 to 5.0 (condition grade)\n"
        "• `odometer` - Mileage in miles\n"
        "• `region` - NE, SE, MW, SW, W\n\n"
        
        "*Year/Make/Model Lookup:*\n"
        "• `/ymm 2020 Honda Accord`\n\n"
        
        "*Testing Example:*\n"
        "• Test VIN (UAT): `WBA3C1C5XFP853102`\n\n"
        
        "💡 After a search, use the interactive 'Refine Valuation' button to adjust parameters with a user-friendly interface.",
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
    
    if "grade" in query_params:
        try:
            # Ensure grade is a float between 0 and 5
            grade = float(query_params["grade"])
            if not 0 <= grade <= 5:
                logger.warning(f"Grade out of range: {grade}. Must be between 0 and 5")
                query_params["grade"] = None
            else:
                query_params["grade"] = grade
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

# Data storage for conversation context
user_data_dict = {}

async def vin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get auction data for a specific VIN with optional parameters."""
    if not context.args:
        await update.message.reply_text(
            "❓ *Please provide a VIN*\n\n"
            "*Examples:*\n"
            "• `/vin 1HGCM82633A123456`\n"
            "• `/vin 1HGCM82633A123456 SE`\n"
            "• `/vin WBA3C1C5XFP853102 color=WHITE grade=3.5 odometer=20000`\n\n"
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
                        value = float(value)
                        if not 0 <= value <= 5:
                            await update.message.reply_text(
                                f"⚠️ *Warning*: Grade must be between 0 and 5. Using default value.",
                                parse_mode="Markdown"
                            )
                            continue
                    except ValueError:
                        await update.message.reply_text(
                            f"⚠️ *Warning*: Invalid grade '{value}'. Must be a number between 0 and 5. Using default value.",
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
            
        # Format and send the response
        message = format_auction_data(data)
        await update.message.reply_text(message, parse_mode="Markdown")
        
        # Store data for potential refinement and transaction viewing
        user_id = update.effective_user.id
        user_data_dict[user_id] = {
            'vin': vin,
            'subseries': subseries,
            'transmission': transmission,
            'params': query_params,
            'data': data  # Store full data response
        }
        
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
                text=f"📊 Refined Valuation Results:\n\n{message}"
            )
            
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
    """Display all transactions for a VIN."""
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
    
    # Create a detailed message with all transactions
    message = f"📋 *All Transactions for VIN:* `{vin}`\n\n"
    
    for i, tx in enumerate(transactions, 1):
        message += f"*Transaction #{i}*\n"
        
        if "price" in tx:
            message += f"• *Price:* ${tx.get('price', 0):,.2f}\n"
        
        if "saleDate" in tx:
            sale_date = tx.get('saleDate', '').split('T')[0]  # Format ISO date
            message += f"• *Date:* {sale_date}\n"
        
        if "odometer" in tx:
            message += f"• *Mileage:* {tx.get('odometer', 0):,} miles\n"
        
        if "conditionGrade" in tx:
            message += f"• *Condition:* {tx.get('conditionGrade', 'N/A')}/5.0\n"
        
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
    
    # Split message if it's too long
    MAX_MESSAGE_LENGTH = 4096  # Telegram's limit
    
    if len(message) <= MAX_MESSAGE_LENGTH:
        await query.edit_message_text(message, parse_mode="Markdown")
    else:
        # Send initial message
        await query.edit_message_text("Sending transaction details...")
        
        # Split into multiple messages
        for i in range(0, len(message), MAX_MESSAGE_LENGTH):
            chunk = message[i:i + MAX_MESSAGE_LENGTH]
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

def get_ymm_valuation(year, make, model, trim=None):
    """Get valuation data for Year/Make/Model from Manheim API."""
    # Validate YMM parameters
    is_valid, error_msg = validate_ymm(year, make, model)
    if not is_valid:
        logger.error(f"Invalid YMM parameters: {error_msg} - {year}/{make}/{model}")
        return None
    
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
            "*Example:* `/ymm 2020 Honda Accord`",
            parse_mode="Markdown"
        )
        return

    year = context.args[0]
    make = context.args[1]
    model = " ".join(context.args[2:])
    
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
    
    await update.message.reply_text(
        f"🔍 *Searching for:* `{year} {make} {model}`...",
        parse_mode="Markdown"
    )
    
    try:
        # Get vehicle data from Manheim API
        data = get_ymm_valuation(year, make, model)
        
        if not data:
            await update.message.reply_text(
                f"❌ *No auction data found for {year} {make} {model}*",
                parse_mode="Markdown"
            )
            return
            
        # Format and send the response
        message = format_auction_data(data)
        await update.message.reply_text(message, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Error fetching YMM data: {e}")
        await update.message.reply_text(
            f"⚠️ *Error fetching data for {year} {make} {model}*\nPlease try again later.",
            parse_mode="Markdown"
        )

def format_auction_data(data):
    """Format the auction data into a readable message based on Manheim Valuations API structure."""
    if not isinstance(data, dict):
        return f"🚗 *Vehicle Auction Data*\n\n{str(data)}"
    
    message = "🚗 *Vehicle Auction Data*\n\n"
    
    # Vehicle information
    if "vehicle" in data:
        vehicle = data["vehicle"]
        message += "📋 *Vehicle Info*\n"
        if "year" in vehicle and "make" in vehicle and "model" in vehicle:
            message += f"• *{vehicle.get('year')} {vehicle.get('make')} {vehicle.get('model')}"
            if "trim" in vehicle:
                message += f" {vehicle.get('trim')}"
            message += "*\n"
        if "vin" in vehicle:
            message += f"• VIN: `{vehicle.get('vin')}`\n"
        if "style" in vehicle:
            message += f"• Style: {vehicle.get('style')}\n"
        if "engineSize" in vehicle:
            message += f"• Engine: {vehicle.get('engineSize')}\n"
        if "transmission" in vehicle:
            message += f"• Transmission: {vehicle.get('transmission')}\n"
        if "drivetrain" in vehicle:
            message += f"• Drivetrain: {vehicle.get('drivetrain')}\n"
        message += "\n"
    
    # Wholesale value ranges
    if "wholesaleAverages" in data:
        message += "💰 *Wholesale Values*\n"
        wholesale = data["wholesaleAverages"]
        
        # Aggregate average
        if "aggregateAverage" in wholesale:
            agg = wholesale["aggregateAverage"]
            if "average" in agg:
                message += f"• *Aggregate Average:* ${agg.get('average', 0):,.2f}\n"
            if "rough" in agg and "clean" in agg:
                message += f"  Range: ${agg.get('rough', 0):,.2f} - ${agg.get('clean', 0):,.2f}\n"
        
        # Adjusted MMR
        if "adjustedMMR" in wholesale:
            adj = wholesale["adjustedMMR"]
            if "average" in adj:
                message += f"• *Adjusted MMR:* ${adj.get('average', 0):,.2f}\n"
            if "rough" in adj and "clean" in adj:
                message += f"  Range: ${adj.get('rough', 0):,.2f} - ${adj.get('clean', 0):,.2f}\n"
        
        # Base MMR
        if "baseMMR" in wholesale:
            base = wholesale["baseMMR"]
            if "average" in base:
                message += f"• *Base MMR:* ${base.get('average', 0):,.2f}\n"
        
        message += "\n"
    
    # Recent auction transactions
    if "marketSummary" in data and "transactions" in data["marketSummary"]:
        transactions = data["marketSummary"]["transactions"]
        if transactions:
            # Store transactions for potential detailed view
            data["transaction_count"] = len(transactions)
            
            message += f"🔄 *Recent Transactions* ({len(transactions)} total)\n"
            for i, tx in enumerate(transactions[:3], 1):  # Show only 3 in the summary view
                sale_info = []
                
                if "price" in tx:
                    sale_info.append(f"${tx.get('price', 0):,.2f}")
                
                if "saleDate" in tx:
                    sale_date = tx.get('saleDate', '').split('T')[0]  # Format ISO date
                    sale_info.append(f"{sale_date}")
                
                message += f"*{i}.* {' on '.join(sale_info)}\n"
                
                details = []
                if "odometer" in tx:
                    details.append(f"{tx.get('odometer', 0):,} miles")
                if "conditionGrade" in tx:
                    details.append(f"Grade: {tx.get('conditionGrade', 'N/A')}/5.0")
                if "location" in tx:
                    details.append(f"{tx.get('location', 'N/A')}")
                
                if details:
                    message += f"   _({' | '.join(details)})_\n"
                
            message += "\n"
            
            # Add note about viewing all transactions if there are more than shown
            if len(transactions) > 3:
                message += f"_...and {len(transactions) - 3} more transactions. Use the button below to view all._\n\n"
            
    # Market statistics
    if "marketSummary" in data and "statistics" in data["marketSummary"]:
        stats = data["marketSummary"]["statistics"]
        message += "📊 *Market Summary*\n"
        
        if "averagePrice" in stats:
            message += f"• *Avg Price:* ${stats.get('averagePrice', 0):,.2f}\n"
        if "averageOdometer" in stats:
            message += f"• *Avg Mileage:* {stats.get('averageOdometer', 0):,} miles\n"
        if "averageConditionGrade" in stats:
            message += f"• *Avg Condition:* {stats.get('averageConditionGrade', 0):.1f}/5.0\n"
        if "transactionCount" in stats:
            message += f"• *Total Transactions:* {stats.get('transactionCount', 0)}\n"
    
    return message

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
    
    # Add callback handlers
    application.add_handler(CallbackQueryHandler(view_all_transactions_callback, pattern="^view_all_transactions$"))
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