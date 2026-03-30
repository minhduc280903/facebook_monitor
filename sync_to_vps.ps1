# ========================================
# SYNC TO VPS - Single Archive Upload
# ========================================

$VPS_HOST = "root@149.28.150.95"
$VPS_PATH = "/opt/facebook-scraper"
$TEMP_ARCHIVE = "facebook-scraper.tar.gz"

Write-Host "Creating archive..." -ForegroundColor Green

# Create file list with only existing items
$FilesToInclude = @()
$DirsToInclude = @("api", "core", "scrapers", "utils", "webapp_streamlit", "migrations")
$SingleFiles = @("*.py", "account.txt", "proxies.txt", "targets.json", "selectors.json", "requirements.txt", "config.py", ".ngrok_token", "setup_ubuntu.sh", "DEPLOY_TO_VPS.md")

# Add directories that exist
foreach ($dir in $DirsToInclude) {
    if (Test-Path $dir) {
        $FilesToInclude += $dir
    }
}

# Add individual files (using wildcards)
foreach ($file in $SingleFiles) {
    $FilesToInclude += $file
}

# Create archive
tar -czf $TEMP_ARCHIVE `
    --exclude='__pycache__' `
    --exclude='*.pyc' `
    --exclude='venv' `
    --exclude='logs' `
    --exclude='sessions' `
    --exclude='test_sessions' `
    --exclude='screenshots' `
    --exclude='*.log' `
    $FilesToInclude

if (-not (Test-Path $TEMP_ARCHIVE)) {
    Write-Host "ERROR: Failed to create archive!" -ForegroundColor Red
    exit 1
}

Write-Host "Archive created: $(Get-Item $TEMP_ARCHIVE | Select-Object -ExpandProperty Length) bytes" -ForegroundColor Green
Write-Host "Uploading archive (ONLY 1 PASSWORD!)..." -ForegroundColor Yellow

# Upload archive (ONLY 1 TIME!)
scp $TEMP_ARCHIVE "${VPS_HOST}:${VPS_PATH}/"

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Upload failed!" -ForegroundColor Red
    Remove-Item $TEMP_ARCHIVE -ErrorAction SilentlyContinue
    exit 1
}

Write-Host "Extracting on VPS..." -ForegroundColor Yellow

# Extract on VPS
ssh $VPS_HOST "cd ${VPS_PATH} && tar -xzf ${TEMP_ARCHIVE} && rm ${TEMP_ARCHIVE}"

# Clean up local archive
Remove-Item $TEMP_ARCHIVE -ErrorAction SilentlyContinue

Write-Host "Sync complete! (Only 2 passwords: scp + ssh)" -ForegroundColor Green
