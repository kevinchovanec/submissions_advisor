#!/bin/bash
# Submissions Advisor — local launcher for Mac/Linux
# Copy to launch.sh, make executable (chmod +x launch.sh), then double-click or run ./launch.sh

cd "$(dirname "$0")"

# Activate the conda environment
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate submission_advisor

python launch_app.py
