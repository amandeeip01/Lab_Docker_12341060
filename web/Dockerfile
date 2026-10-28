# Web front end: nginx serves the UI and forwards API calls to the api service
FROM nginx:1.27-alpine

# Where to find the API; filled into the config by the nginx image at start-up
ENV API_HOST=api \
    API_PORT=8000

# Files in /etc/nginx/templates are run through envsubst into /etc/nginx/conf.d
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY index.html /usr/share/nginx/html/index.html

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
