FROM wordpress:7.1.3-php8.3-apache
RUN apt-get update && apt-get install -y --no-install-recommends curl unzip && \
    curl -fsSL https://downloads.wordpress.org/plugin/woocommerce.11.2.1.zip -o /tmp/woocommerce.zip && \
    unzip -q /tmp/woocommerce.zip -d /usr/src/wordpress/wp-content/plugins && rm /tmp/woocommerce.zip && \
    apt-get purge -y curl unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

COPY bootstrap.php /usr/local/bin/urumi-bootstrap.php
