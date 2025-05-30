import json
import os
from datetime import datetime
from typing import Dict, Any, List
import shutil
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def store_feedback(contact: str, feedback: str) -> Dict[str, Any]:
    """
    Store feedback to a file in /data directory for Hugging Face Spaces

    Args:
        contact (str): Contact information (email/name)
        feedback (str): Feedback content

    Returns:
        Dict[str, Any]: Result dictionary with status and message

    Raises:
        Exception: If there's an error saving the feedback
    """
    try:
        # Validate inputs
        if not contact or not contact.strip():
            raise ValueError("Contact information is required")

        if not feedback or not feedback.strip():
            raise ValueError("Feedback content is required")

        # Create feedback entry
        feedback_entry = {
            "timestamp": datetime.now().isoformat(),
            "contact": contact.strip(),
            "feedback": feedback.strip()
        }

        # Ensure /data/feedback directory exists
        feedback_dir = "/app/data/feedback"
        try:
            os.makedirs(feedback_dir, exist_ok=True)
            if not os.access(feedback_dir, os.W_OK):
                raise PermissionError(f"No write permission for directory: {feedback_dir}")
        except Exception as e:
            raise Exception(f"Failed to create or access feedback directory: {str(e)}")

        # Create filename with date
        date_str = datetime.now().strftime('%Y-%m-%d')
        filename = os.path.join(feedback_dir, f"feedback_{date_str}.json")
        temp_filename = f"{filename}.tmp"

        # Read existing feedback for the day or create new list
        feedback_list = _read_feedback_file(filename)

        # Add new feedback
        feedback_list.append(feedback_entry)

        # Write to temporary file first
        try:
            _write_feedback_file(temp_filename, feedback_list)
            
            # Verify the temporary file was written correctly
            if not os.path.exists(temp_filename):
                raise Exception("Failed to create temporary feedback file")
            
            # Verify the temporary file contains valid JSON
            try:
                with open(temp_filename, 'r', encoding='utf-8') as f:
                    json.load(f)
            except json.JSONDecodeError:
                raise Exception("Failed to write valid JSON to temporary file")
            
            # If everything is good, replace the original file
            backup_filename = None # Initialize backup_filename
            if os.path.exists(filename):
                # Create backup of original file
                backup_filename = f"{filename}.bak"
                shutil.copy2(filename, backup_filename)
            
            # Move temporary file to final location
            shutil.move(temp_filename, filename)
            
            # Remove backup if everything succeeded
            if backup_filename and os.path.exists(backup_filename):
                os.remove(backup_filename)
                
        except Exception as e:
            # Clean up temporary file if it exists
            if os.path.exists(temp_filename):
                os.remove(temp_filename)
            raise Exception(f"Failed to write feedback file: {str(e)}")

        # Log to console for immediate visibility
        _log_feedback_to_console(feedback_entry, filename)

        return {
            "status": "success",
            "message": "Feedback saved successfully",
            "timestamp": feedback_entry["timestamp"],
            "filename": filename
        }

    except Exception as e:
        error_msg = f"Error saving feedback: {str(e)}"
        logging.error(error_msg)
        raise Exception(error_msg)


def _read_feedback_file(filename: str) -> List[Dict[str, Any]]:
    """Read feedback from JSON file"""
    try:
        if not os.path.exists(filename):
            return []
            
        if not os.access(filename, os.R_OK):
            raise PermissionError(f"No read permission for file: {filename}")
            
        with open(filename, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError as e:
                # If file is corrupted, try to read backup
                backup_filename = f"{filename}.bak"
                if os.path.exists(backup_filename):
                    logging.warning(f"Warning: Corrupted feedback file {filename}, trying backup")
                    with open(backup_filename, 'r', encoding='utf-8') as backup_f:
                        return json.load(backup_f)
                else:
                    logging.warning(f"Warning: Corrupted feedback file {filename}, starting fresh")
                    return []
    except Exception as e:
        logging.error(f"Error reading feedback file: {str(e)}")
        return []


def _write_feedback_file(filename: str, feedback_list: List[Dict[str, Any]]) -> None:
    """Write feedback to JSON file"""
    try:
        # Ensure the directory exists
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        # Write to file with proper encoding and formatting
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(feedback_list, f, indent=2, ensure_ascii=False)
            
        # Verify the file was written
        if not os.path.exists(filename):
            raise Exception(f"Failed to create file: {filename}")
            
    except Exception as e:
        raise Exception(f"Failed to write feedback file: {str(e)}")


def _log_feedback_to_console(feedback_entry: Dict[str, Any], filename: str) -> None:
    """Log feedback to console for immediate visibility"""
    logging.info("\n" + "="*60)
    logging.info("NEW FEEDBACK RECEIVED")
    logging.info("="*60)
    logging.info(f"Timestamp: {feedback_entry['timestamp']}")
    logging.info(f"Contact: {feedback_entry['contact']}")
    logging.info(f"Feedback: {feedback_entry['feedback']}")
    logging.info(f"Saved to: {filename}")
    logging.info("="*60 + "\n")

def read_out_feedback() -> Dict[str, Any]:
    """
    Read all feedback files from the feedback directory and return their contents
    
    Returns:
        Dict[str, Any]: Dictionary containing all feedback entries organized by date
    """
    try:
        feedback_dir = "/app/data/feedback"
        if not os.path.exists(feedback_dir):
            return {"status": "success", "message": "No feedback files found", "feedback": {}}
            
        if not os.access(feedback_dir, os.R_OK):
            raise PermissionError(f"No read permission for directory: {feedback_dir}")
            
        feedback_data = {}
        
        # Read all feedback files
        for filename in os.listdir(feedback_dir):
            if filename.endswith('.json'):
                file_path = os.path.join(feedback_dir, filename)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        feedback_entries = json.load(f)
                        # Use the date from filename as key
                        date_key = filename.replace('feedback_', '').replace('.json', '')
                        feedback_data[date_key] = feedback_entries
                except Exception as e:
                    logging.error(f"Error reading feedback file {filename}: {str(e)}")
                    continue
                    
        return {
            "status": "success",
            "message": "Feedback retrieved successfully",
            "feedback": feedback_data
        }
        
    except Exception as e:
        error_msg = f"Error reading feedback: {str(e)}"
        logging.error(error_msg)
        raise Exception(error_msg)