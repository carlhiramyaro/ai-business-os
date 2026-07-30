# Three stages so the final image only carries what `node server.js`
# actually needs at runtime -- not the full node_modules tree, dev
# dependencies, or the source .tsx files. See docs/infra-guide.md.

# ---- deps: install exactly what's in package-lock.json ----
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# ---- dev: hot-reloading dev server, used only by docker-compose.yml ----
# Not part of the deploy path (docker-compose.prod.yml pulls the `runner`
# stage's image from ECR instead) -- this stage exists purely so local
# Compose gets the same edit-and-see-it Next.js dev experience the bare
# `npm run dev` run-book had, instead of a rebuild-per-change production
# bundle.
FROM node:22-alpine AS dev
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev"]

# ---- builder: compile the app ----
FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* vars are inlined into the client JS bundle at *build* time,
# not read at runtime -- unlike every other env var in this project. That
# makes this web image environment-specific: it must be rebuilt per target
# (dev/prod), it cannot be built once and promoted between environments the
# way the api/worker/beat image can. See docs/infra-guide.md's "Next.js in
# Docker" section and docs/learning-guide.md section 3.3.
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

RUN npm run build

# ---- runner: the minimal standalone server ----
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs

# next.config.ts's output: "standalone" traces exactly the files server.js
# needs and copies them here; static assets and public/ are deliberately
# excluded from that trace (meant for a CDN) so they're copied by hand.
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
