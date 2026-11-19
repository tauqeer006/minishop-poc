FROM mongo:7.0

COPY init/mongo-healthcheck.sh /usr/local/bin/mongo-healthcheck.sh
# Strip CRLF in case the repo was extracted on Windows.
RUN sed -i 's/\r$//' /usr/local/bin/mongo-healthcheck.sh && chmod +x /usr/local/bin/mongo-healthcheck.sh

EXPOSE 27017

# Single-node replica set (required for multi-document transactions).
# No keyFile/auth: development POC only.
CMD ["mongod", "--replSet", "rs0", "--bind_ip_all", "--port", "27017"]
