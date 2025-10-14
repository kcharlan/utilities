# Snapshots

This directory contains snapshots of the collected LLM usage data. Snapshots are created automatically by the data collection server whenever the `/reset` endpoint is called.

## Filename Convention

The snapshots are named using the following convention:

`snapshot_<timestamp>.json`

Where `<timestamp>` is a Unix timestamp in milliseconds representing the time the snapshot was created. For example, `snapshot_1760327682560.json` was created at the time represented by the timestamp `1760327682560`.

## Format

The snapshots are JSON files containing the collected usage data at the time of the reset. The format of the data is an object where the keys are hostnames and the values are the total token counts for that host.

```json
{
  "totals": {
    "chat.openai.com": 12345,
    "bard.google.com": 67890
  }
}
```