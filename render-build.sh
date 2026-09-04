#!/usr/bin/env bash
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

# تحديد مسار ثابت لتثبيت متصفح Playwright لتجنب أي أخطاء في المسارات
export PLAYWRIGHT_BROWSERS_PATH=/opt/render/project/src/pw-browsers
playwright install chromium
