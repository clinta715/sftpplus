#!/bin/bash

DESTINATION_DIRECTORY="$1"

if [[ "$1" == "init" ]]; then
    if [[ -z "$2" ]]; then
        echo "Usage: $0 init <number_of_days>"
        exit 1
    fi
    echo "$(date '+%Y-%m-%d')" > init_date
    echo "$2" > init_days
    exit 0
fi

if [[ ! -f "init_date" || ! -f "init_days" ]]; then
    echo "Please run the script with 'init' parameter to initialize and specify the number of days."
    exit 1
fi

CURRENT_DATE=$(date '+%Y-%m-%d')
LAST_RUN_DATE=$(cat init_last 2>/dev/null || cat init_date)

if (( ($(date -d "$CURRENT_DATE" +%s) - $(date -d "$LAST_RUN_DATE" +%s)) / 86400 >= $(cat init_days) )); then
    OLDEST_FILE=$(ls -1t "$DESTINATION_DIRECTORY"/*.tar.zst 2>/dev/null | tail -1)
    if [[ -n "$OLDEST_FILE" ]]; then
        rm "$OLDEST_FILE"
    fi
    echo "$CURRENT_DATE" > init_date
fi

tar --zstd -cf "$DESTINATION_DIRECTORY/$CURRENT_DATE.tar.zst" $(find . -type f -newermt "$LAST_RUN_DATE")

echo "$CURRENT_DATE" > init_last
echo "Backup created: $DESTINATION_DIRECTORY/$CURRENT_DATE.tar.zst"
