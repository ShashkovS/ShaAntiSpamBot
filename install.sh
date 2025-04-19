# Настраиваем dns для нового поддомена
# ...

# Настраиваем ssl для нового поддомена
sudo certbot certonly --nginx -d shaantispambot.shashkovs.ru
   # /etc/letsencrypt/live/shaantispambot.shashkovs.ru/fullchain.pem
   # Your key file has been saved at:
   # /etc/letsencrypt/live/shaantispambot.shashkovs.ru/privkey.pem


# Содержимое каждого сайта будет находиться в собственном каталоге, поэтому создаём нового пользователя
sudo useradd shaantispambot -m -U
mkdir /web/shaantispambot


# Делаем каталоги для данных сайта (файлы сайта, логи и временные файлы):
sudo mkdir -p -m 770 /web/shaantispambot/logs
sudo mkdir -p -m 770 /web/shaantispambot/tmp

# Делаем юзера и его группу владельцем  всех своих папок
sudo chown -R shaantispambot:shaantispambot /web/shaantispambot
# Делаем так, чтобы всё новое лежало в группе
# Изменяем права доступа на каталог
sudo chmod -R 2770 /web/shaantispambot

# Чтобы Nginx получил доступ к файлам сайта, добавим пользователя nginx в группу
sudo usermod -a -G shaantispambot nginx
sudo usermod -a -G shaantispambot serge
sudo usermod -a -G shaantispambot root
sudo usermod -a -G web shaantispambot


sudo chgrp -R shaantispambot /web/shaantispambot
sudo chmod  770 /web/shaantispambot
sudo find /web/shaantispambot -type d -exec chmod 2770 '{}' \;
sudo setfacl -R -d -m group:shaantispambot:rwx /web/shaantispambot
sudo setfacl -R -m group:shaantispambot:rwx /web/shaantispambot















# Клонируем репу
cd /web/shaantispambot
sudo -H -u shaantispambot git clone git@github.com:ShashkovS/shaantispambot.git shaantispambot
cd /web/shaantispambot/shaantispambot
sudo -H -u shaantispambot git checkout main
sudo -H -u shaantispambot git pull

# виртуальное окружение
cd /web/shaantispambot
python3.13 -m venv --without-pip shaantispambot_env
source /web/shaantispambot/shaantispambot_env/bin/activate.fish
curl https://bootstrap.pypa.io/get-pip.py | /web/shaantispambot/shaantispambot_env/bin/python3.13
deactivate
source /web/shaantispambot/shaantispambot_env/bin/activate.fish
pip install --upgrade shaantispambot/
deactivate


# секреты
mkdir /web/shaantispambot/shaantispambot/config
sudo nano /web/shaantispambot/shaantispambot/config/secrets.json
{
...
}


sudo chown -R shaantispambot:shaantispambot /web/shaantispambot


# Настраиваем systemd для поддержания приложения в рабочем состоянии
# Начинаем с описания сервиса
sudo tee /web/shaantispambot/gunicorn.shaantispambot.service << 'EOF'
[Unit]
Description=Gunicorn instance to serve shaantispambot
After=network.target

[Service]
PIDFile=/web/shaantispambot/shaantispambot.pid
Restart=always
RestartSec=0
User=shaantispambot
Group=nginx
RuntimeDirectory=gunicorn
WorkingDirectory=/web/shaantispambot/shaantispambot
Environment="PATH=/web/shaantispambot/shaantispambot_env/bin"
ExecStart=/web/shaantispambot/shaantispambot_env/bin/gunicorn  --pid /web/shaantispambot/shaantispambot.pid  --workers 1  --bind unix:/web/shaantispambot/shaantispambot.socket --worker-class aiohttp.GunicornUVLoopWebWorker -m 007  main:app
ExecReload=/bin/kill -s HUP $MAINPID
ExecStop=/bin/kill -s TERM $MAINPID
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

sudo ln -s /web/shaantispambot/gunicorn.shaantispambot.service /etc/systemd/system/gunicorn.shaantispambot.service

# Тестовый запуск
cd /web/shaantispambot/shaantispambot && export PROD=true && sudo -H -u shaantispambot /web/shaantispambot/shaantispambot_env/bin/gunicorn  --pid /web/shaantispambot/shaantispambot.pid  --workers 1  --bind unix:/web/shaantispambot/shaantispambot.socket --worker-class aiohttp.GunicornUVLoopWebWorker -m 007  main:app

# От имени shaantispambot
sudo su - shaantispambot
cd /web/shaantispambot/shaantispambot && export PROD=true && /web/shaantispambot/shaantispambot_env/bin/gunicorn  --pid /web/shaantispambot/shaantispambot.pid  --workers 1  --bind unix:/web/shaantispambot/shaantispambot.socket --worker-class aiohttp.GunicornUVLoopWebWorker -m 007  main:app



# Настраиваем nginx (здесь настройки СТРОГО отдельного домена или поддомена). Если хочется держать в папке, то настраивать nginx нужно по-другому
echo '
    server {
        listen [::]:443 ssl; # managed by Certbot
        listen 443 ssl; # managed by Certbot
        http2 on;
        server_name shaantispambot.shashkovs.ru; # managed by Certbot

        ssl_certificate /etc/letsencrypt/live/shaantispambot.shashkovs.ru/fullchain.pem; # managed by Certbot
        ssl_certificate_key /etc/letsencrypt/live/shaantispambot.shashkovs.ru/privkey.pem; # managed by Certbot
        include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
        ssl_dhparam /etc/pki/nginx/dhparam.pem;
        add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
        location /api {
          proxy_set_header Host $http_host;
          proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          proxy_redirect off;
          proxy_buffering off;
          proxy_pass http://unix:/web/shaantispambot/shaantispambot.socket;
        }
    }
' > /web/shaantispambot/shaantispambot.conf

sudo ln -s /web/shaantispambot/shaantispambot.conf /etc/nginx/conf.d/shaantispambot.conf

# Проверяем корректность конфига. СУПЕР-ВАЖНО!
sudo nginx -t
# Перезапускаем nginx
sudo systemctl reload nginx.service


# Говорим, что нужен автозапуск
sudo systemctl enable gunicorn.shaantispambot
# Запускаем
sudo systemctl start gunicorn.shaantispambot
sudo journalctl -u gunicorn.shaantispambot --since "5 minutes ago"
# Проверяем
curl --unix-socket /web/shaantispambot/shaantispambot.socket http

cd /web/shaantispambot/shaantispambot
sudo -H -u shaantispambot git checkout main
sudo -H -u shaantispambot git pull


sudo systemctl daemon-reload
sudo systemctl stop gunicorn.shaantispambot
sudo systemctl start gunicorn.shaantispambot
sudo journalctl -u gunicorn.shaantispambot --since "1 minutes ago"
sudo journalctl -u gunicorn.shaantispambot --since "1 minutes ago" -f

sudo systemctl stop gunicorn.shaantispambot
