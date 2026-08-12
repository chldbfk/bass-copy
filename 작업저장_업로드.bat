@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   오늘 작업 GitHub 업로드
echo ============================================
echo.

echo [1/4] 협업자의 최신 변경사항 받아오는 중 (git pull)...
git pull origin main
if errorlevel 1 (
    echo.
    echo [오류] pull에 실패했습니다. 충돌이 있을 수 있으니 직접 확인해주세요.
    pause
    exit /b 1
)

echo.
echo [2/4] 오늘 바뀐 파일 확인 중...
echo.
git status --short
echo.

set "COMMIT_MSG="
set /p COMMIT_MSG="오늘 작업 내용을 한 줄로 입력하세요 (예: 오디티스 곡 리듬 수정): "

if "%COMMIT_MSG%"=="" (
    echo.
    echo [알림] 입력한 내용이 없어 종료합니다. 아무것도 업로드되지 않았습니다.
    pause
    exit /b 0
)

echo.
echo [3/4] 변경사항 저장 중 (git add + commit)...
git add .
git commit -m "%COMMIT_MSG%"
if errorlevel 1 (
    echo.
    echo [알림] 새로 커밋할 변경사항이 없습니다. ^(이미 최신 상태거나 오류^)
    pause
    exit /b 0
)

echo.
echo [4/4] GitHub에 업로드 중 (git push)...
git push origin main
if errorlevel 1 (
    echo.
    echo [오류] push에 실패했습니다. 인터넷 연결이나 권한을 확인해주세요.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   완료! GitHub에 오늘 작업이 업로드됐습니다.
echo   https://github.com/chldbfk/bass-copy
echo ============================================
pause
