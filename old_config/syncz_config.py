import argparse
import yaml
import os
from syncz_logging_utils import logger

def parse_arguments():
    parser = argparse.ArgumentParser(description=__file__)
    parser.add_argument('--base_command', help='Base command', required=True)
    parser.add_argument('--base_dest_path', help='Value for base_dest_path')
    parser.add_argument('--base_dest_host', help='Value for base_dest_host')
    parser.add_argument('--base_source_path', help='Value for base_source_path', required=True)
    return parser.parse_args()

def read_smtp_config():
    try:
        with open("smtp.txt", "r") as f:
            smtp_server = f.readline().strip()
            dest_email = f.readline().strip()
            source_email = f.readline().strip()
            base_work_path = f.readline().strip()
        return smtp_server, dest_email, source_email, base_work_path
    except FileNotFoundError:
        logger.error("Error: smtp.txt not found")
        raise

def load_commands():
    script_dir = os.path.dirname(os.path.realpath(__file__))
    yaml_path = os.path.join(script_dir, 'syncz_commands.yaml')
    try:
        with open(yaml_path, 'r') as file:
            data = yaml.safe_load(file)
            return data["commands"]
    except FileNotFoundError:
        logger.error(f"Error: {yaml_path} not found")
        raise
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML file: {e}")
        raise
