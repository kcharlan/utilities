FROM node:24-alpine
WORKDIR /srv
COPY package.json ./
RUN npm install --omit=dev --no-package-lock
