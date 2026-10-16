FROM node:20-alpine
WORKDIR /srv/apps/web
COPY apps/web/package.json ./
RUN npm install
COPY apps/web ./
EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", "3000"]
