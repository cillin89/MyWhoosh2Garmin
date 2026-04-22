import logging
import sys
import traceback
from pathlib import Path

from fit_utils.fit_builder import MyWhooshFitBuilder
from garmin.utils import (
    authenticate_to_garmin,
    list_virtual_cycling_activities,
    upload_fit_file_to_garmin,
)
from strava.client import StravaClientBuilder
from strava.utils import sanitize_filename

SCRIPT_DIR = Path(__file__).resolve().parent
log_file_path = SCRIPT_DIR / "myWhoosh2Garmin.log"
RAW_FIT_FILE_PATH = SCRIPT_DIR / "data" / "raw"

# --- LOGGING SETUP ---
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

# 1. File Handler (Keeps local logging working)
file_handler = logging.FileHandler(log_file_path)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# 2. Stream Handler (CRITICAL for GitHub Actions visibility)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)


def main():
    try:
        logger.info("Starting MyWhoosh to Garmin sync process...")
        
        logger.debug("Authenticating to Garmin...")
        authenticate_to_garmin()
        
        logger.debug("Building Strava client...")
        client_builder = StravaClientBuilder()
        client = client_builder.with_auth().with_cookies().build()

        logger.debug("Fetching Strava activities...")
        strava_retrieved_activities = client.get_filtered_activities()
        
        logger.debug("Fetching Garmin activities...")
        names, start_times = list_virtual_cycling_activities(last_n_days=7)

        def strip_timezone(dt):
            if dt.tzinfo is not None:
                return dt.replace(tzinfo=None)
            return dt

        start_times_no_tz = {strip_timezone(dt) for dt in start_times}

        new_activities = [
            activity
            for activity in strava_retrieved_activities
            if strip_timezone(activity.start_date_local) not in start_times_no_tz
        ]
        
        logger.info(
            f"Found {len(new_activities)} new virtual cycling activities to upload to Garmin."  # noqa: E501
        )

        for activity in new_activities:
            logger.info(f"Processing activity: {activity.name} (ID: {activity.id})")
            client.downloader.download_activity(activity.id)
            safe_name = sanitize_filename(activity.name)
            file_name = f"{safe_name}.json"
            input_path = RAW_FIT_FILE_PATH / file_name
            output_path = RAW_FIT_FILE_PATH.parent / "processed" / f"{safe_name}.fit"
            
            logger.debug(f"Building FIT file for {safe_name}...")
            builder = MyWhooshFitBuilder(input_path)
            builder.build(output_path)
            
            logger.debug(f"Uploading {safe_name} to Garmin...")
            upload_fit_file_to_garmin(output_path)
            
            try:
                output_path.unlink()
                logger.info(f"Successfully uploaded and deleted file: {output_path}")
            except Exception as e:
                logger.error(f"Failed to delete file {output_path}: {e}")
                
        logger.info("Sync process completed successfully.")

    except Exception as e:
        # If ANYTHING fails, explicitly log the full traceback to the console before dying
        logger.error("A critical error occurred that crashed the script:")
        logger.error(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    main()
