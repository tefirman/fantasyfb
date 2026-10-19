# Deploying to Google Cloud Run

Cloud Run runs the same container as `app/Dockerfile`. It scales to zero when idle, so a few users stay inside the free allowance. Check current limits at https://cloud.google.com/run/pricing before relying on them.

## One-time setup

1. Create a Google Cloud project and link a billing account. Cloud Run requires one even for free-tier use. Add a budget alert (Billing, then Budgets & alerts) at a few dollars.
2. Install the `gcloud` CLI, then:

   ```bash
   gcloud auth login
   gcloud config set project <project-id>
   gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
     artifactregistry.googleapis.com secretmanager.googleapis.com
   gcloud artifacts repositories create fantasyfb --repository-format=docker --location=us-central1
   ```

3. Store the Yahoo credentials as secrets (skip for a Sleeper-only app):

   ```bash
   printf '%s' '<consumer key>'    | gcloud secrets create yahoo-key --data-file=-
   printf '%s' '<consumer secret>' | gcloud secrets create yahoo-secret --data-file=-
   PROJECT_NUMBER=$(gcloud projects describe $(gcloud config get-value project) --format='value(projectNumber)')
   for s in yahoo-key yahoo-secret; do
     gcloud secrets add-iam-policy-binding $s \
       --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
       --role=roles/secretmanager.secretAccessor
   done
   ```

## Build and deploy

From the repo root:

```bash
gcloud builds submit --config deploy/cloudrun/cloudbuild.yaml .

gcloud run deploy fantasyfb-web \
  --image us-central1-docker.pkg.dev/$(gcloud config get-value project)/fantasyfb/fantasyfb-web:latest \
  --region us-central1 \
  --memory 2Gi --cpu 1 \
  --min-instances 0 --max-instances 1 \
  --no-cpu-throttling \
  --allow-unauthenticated \
  --set-secrets CONSUMER_KEY=yahoo-key:latest,CONSUMER_SECRET=yahoo-secret:latest
```

Why these flags:

- `--max-instances 1`: sessions and jobs live in memory, so a second instance would lose them.
- `--no-cpu-throttling`: runs take minutes in a child process. By default Cloud Run only gives CPU while a request is being handled, which can stall a run between status polls. This switches to instance-based billing, which has its own free allowance.
- `--memory 2Gi`: a run loads about two seasons of nflverse data. Cloud Run's filesystem is in memory, so the data cache counts against this too. Raise it if a run is killed for memory.
- `--allow-unauthenticated`: so friends can open it without a Google login.

## Yahoo redirect URI

The service URL (`https://fantasyfb-web-....run.app`) is only known after the first deploy, so Yahoo sign-in needs a second pass:

1. Redeploy with the callback set:

   ```bash
   gcloud run services update fantasyfb-web --region us-central1 \
     --set-env-vars YAHOO_REDIRECT_URI=https://<service-url>/auth/yahoo/callback
   ```

2. Add that exact URI to your Yahoo app at https://developer.yahoo.com/apps/. The app refuses a mismatch.

Sleeper works before this step.

## Things to expect

- After about 15 idle minutes the instance scales to zero. The next visit takes a few seconds to start, and the first run is slower because the nflverse cache is empty.
- A restart loses sessions and finished reports. Users sign in again.
- To update, run the build and deploy commands again. The image installs from your local checkout, so commit or not as you like.
- Other settings (`FANTASYFB_RUN_TIMEOUT`, `FANTASYFB_ENABLE_MOVES`, and so on) are listed in `app/README.md` and are passed with `--set-env-vars`.
