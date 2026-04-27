FROM kuzudb/explorer:latest

# Patch the default query in the built Vue bundle:
#   MATCH (a)-[r]->(b) RETURN * LIMIT 5;
#     → MATCH (a)-[r]->(b) RETURN * LIMIT 1000;
#
# The string is a quoted literal in the webpack bundle so sed can reliably
# find and replace it without touching any surrounding minified code.
USER root
RUN find /home/node/app/dist -name "*.js" -exec \
    sed -i 's/MATCH (a)-\[r\]->(b) RETURN \* LIMIT 5;/MATCH (a)-[r]->(b) RETURN * LIMIT 1000;/g' {} +
USER node
