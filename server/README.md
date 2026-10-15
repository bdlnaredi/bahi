# Bahi server

This folder is the Docker image for Bahi. For the full step-by-step setup with screenshots, see the
[installation guide](https://github.com/bdlnaredi/bahi/blob/main/docs/INSTALL.md) and the
[user guide](https://github.com/bdlnaredi/bahi/blob/main/docs/USING.md).

Quick reference:

- Image: `ghcr.io/bdlnaredi/bahi:latest`, port `8780`, data in `/data`
- Required environment variables: `APP_PASSWORD` (phone app login) and `SYNC_TOKEN` (shared with the Tally PC agent)
- Build it yourself: `docker build -t bahi:local .`
