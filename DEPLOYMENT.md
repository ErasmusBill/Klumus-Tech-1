# VPS deployment for `school.fruitfulyouth.org`

For local Windows setup without Docker, use [WINDOWS_DEVELOPMENT.md](WINDOWS_DEVELOPMENT.md).

This project is set up to run Django in Docker on `127.0.0.1:8000` and let the VPS Nginx handle public traffic on ports `80/443`.

## DNS

In Namecheap:

- Create or update an `A` record for `school` pointing to your Hostinger VPS public IP.
- Optional: create/update the root `A` record for `fruitfulyouth.org` if you also want the main domain on the same server.

## App startup

From the project directory:

```bash
cp .env.example .env
docker compose build
docker compose up -d
```

The app container will be reachable only on `127.0.0.1:8000`, which avoids conflicts with host Nginx.

## Nginx

Copy [nginx/school.fruitfulyouth.org.conf](/Users/erasmus/Desktop/Klumus-Tech-1/nginx/school.fruitfulyouth.org.conf:1) to your VPS Nginx sites config, for example:

```bash
sudo cp nginx/school.fruitfulyouth.org.conf /etc/nginx/sites-available/school.fruitfulyouth.org
sudo ln -s /etc/nginx/sites-available/school.fruitfulyouth.org /etc/nginx/sites-enabled/school.fruitfulyouth.org
sudo nginx -t
sudo systemctl reload nginx
```

## SSL

After DNS is pointing correctly:

```bash
sudo certbot --nginx -d school.fruitfulyouth.org
```

If Certbot enables HTTPS, keep these env values enabled in `.env`:

```env
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
```

## Notes

- Do not publish Docker Nginx on port `80` on the VPS unless you explicitly use `make up-with-docker-nginx`.
- `school.fruitfulyouth.org` is the public app URL.
- The root domain `fruitfulyouth.org` should only be added to `ALLOWED_HOSTS` if you plan to serve it from this same app.
