set projectRoot to "/Users/martyjazz/Projects/BOT/web_kp"

try
	set dlg to display dialog "Пароль root:" default answer "" with hidden answer buttons {"Отмена", "Проверить"} default button "Проверить"
	set deployPass to text returned of dlg
on error
	return
end try

set cmd to "export DEPLOY_PASS=" & quoted form of deployPass & " ; /bin/sh " & quoted form of (projectRoot & "/test_ssh_askpass.sh")
try
	set out to do shell script cmd with timeout 30
	display alert "SSH OK" message out buttons {"OK"} default button "OK"
on error errMsg
	display alert "SSH не отвечает" message errMsg as critical
end try
