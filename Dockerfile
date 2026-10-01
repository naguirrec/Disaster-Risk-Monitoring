FROM node:22-bookworm-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
ENV INFERENCE_URL=http://inference:43124
RUN npm run build

EXPOSE 43123
CMD ["npx", "next", "start", "-H", "0.0.0.0", "-p", "43123"]
