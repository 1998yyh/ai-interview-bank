location = /ai-interview-bank {
    return 308 /ai-interview-bank/;
}

location ^~ /ai-interview-bank/ {
    alias /var/www/ai-interview-bank/public/;
    index index.html;
}
