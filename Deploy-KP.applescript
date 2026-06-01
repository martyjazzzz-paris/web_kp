-- Деплой БЕЗ Terminal.app: двойной клик или Script Editor → Run
-- Путь к проекту:
set projectRoot to "/Users/martyjazz/Projects/BOT/web_kp"

try
	display notification "KP: введите пароль root…" with title "Deploy v60"
	set dlg to display dialog "Пароль root для 72.56.237.74:" default answer "" with hidden answer buttons {"Отмена", "Деплой"} default button "Деплой"
	set deployPass to text returned of dlg
on error
	return
end try

set logFile to "/tmp/kp-deploy-" & (do shell script "date +%Y%m%d-%H%M%S")
set deployScript to projectRoot & "/deploy_askpass.sh"
set shellCmd to "export DEPLOY_PASS=" & quoted form of deployPass & " ; /bin/sh " & quoted form of deployScript & " > " & quoted form of logFile & " 2>&1 ; echo $? > " & quoted form of (logFile & ".exit")

try
	display notification "KP: заливка на сервер (1–5 мин)…" with title "Deploy v60"
	do shell script shellCmd with timeout 600
on error errMsg number errNum
	set tailLog to do shell script "tail -25 " & quoted form of logFile & " 2>/dev/null || echo '(нет лога)'"
	display alert "Ошибка деплоя (" & errNum & ")" message errMsg & return & return & tailLog & return & return & "Лог: " & logFile as critical
	open POSIX file logFile
	return
end try

set exitCode to do shell script "cat " & quoted form of (logFile & ".exit")
if exitCode is not "0" then
	set tailLog to do shell script "tail -25 " & quoted form of logFile
	display alert "Деплой не прошёл" message tailLog buttons {"OK"} default button "OK" as critical
	open POSIX file logFile
	return
end if

set checkCmd to "curl -sS -L --connect-timeout 12 http://72.56.237.74/static/styles.css | grep -m1 design-version || echo FAIL"
set verLine to do shell script checkCmd
if verLine contains "FAIL" then
	display alert "Залито, но CSS снаружи не обновился" message "Cmd+Shift+R в Safari" & return & logFile as warning
else
	display alert "Готово" message verLine & return & "http://72.56.237.74/" buttons {"Открыть сайт"} default button "Открыть сайт"
	do shell script "open http://72.56.237.74/"
end if
