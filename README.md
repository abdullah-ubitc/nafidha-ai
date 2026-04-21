# Libya Customs — Local Docker Compose

Quick helper to run the app with a local MongoDB for development.

Start (build + detach):

```bash
docker-compose up --build -d
```

Stop and remove containers:

```bash
docker-compose down
```

View app logs:

```bash
docker-compose logs -f app
```

Notes:

Alternative run (manual containers):

```bash
# create a network
docker network create libya-net

# run mongo
docker run -d --name libya-mongo --network libya-net -p 27017:27017 mongo:6

# run the app pointing to the mongo container
docker run -p 8000:8000 --name libya-customs \
  --network libya-net \
  -e MONGO_URL='mongodb://libya-mongo:27017' \
  -e DB_NAME='libya_customs_db' \
  libya-customs
```

One-command start
-----------------

You can start the whole stack with a single command using `make` or the included helper script:

```bash
# using make (recommended)
make start

# or using the script
./scripts/start.sh
```

The `make start` target runs `docker-compose up --build -d` for convenience.

https://drive.google.com/drive/folders/1t9DxxZTKPFdInJ-SQpmwkPaj6xhXym1e?usp=sharing
