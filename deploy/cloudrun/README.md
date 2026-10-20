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
   gcloud artifacts repositories create fantasyfb --repository-format=docker --location=us-west1
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
  --image us-west1-docker.pkg.dev/$(gcloud config get-value project)/fantasyfb/fantasyfb-web:latest \
  --region us-west1 \
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

1. Set the callback on the service:

   ```bash
   gcloud run services update fantasyfb-web --region us-west1 \
     --set-env-vars YAHOO_REDIRECT_URI=https://<service-url>/auth/yahoo/callback
   ```

2. Set that exact URI as the redirect URI on your Yahoo app at https://developer.yahoo.com/apps/. In practice Yahoo wants just the one the app sends, so replace any older value (`localhost`, the `run.app` URL) instead of adding to it, and change it again if you change domains. A leftover URI is enough to make sign-in fail. After saving, reopen the app's settings and check the URI is really there: if it didn't save, Yahoo only shows a generic "Something went wrong" page.

Sleeper works before this step.

If you later redeploy with the full `gcloud run deploy` command, add the same `--set-env-vars YAHOO_REDIRECT_URI=...` to it so the variable isn't dropped. `gcloud run services update --image ...` leaves it alone.

## Custom domain (optional)

The `*.run.app` URL is permanent, but you can also serve the app from a subdomain you own, such as `fantasy.example.com`. Cloud Run domain mappings are a preview feature (Google warns about latency and recommends a load balancer for production), which is fine for a small app. us-west1 supports them.

1. Verify the base domain with `gcloud domains verify example.com` (skip if `gcloud domains list-user-verified` already lists it). It asks you to add a TXT record at your registrar.
2. Map the subdomain:

   ```bash
   gcloud beta run domain-mappings create --service fantasyfb-web \
     --domain fantasy.example.com --region us-west1
   gcloud beta run domain-mappings describe --domain fantasy.example.com --region us-west1
   ```

3. Add the record that `describe` prints under `resourceRecords` at your registrar. For a subdomain it is a CNAME with host `fantasy` and value `ghs.googlehosted.com`. Enter the host as just the subdomain, and leave off the trailing dot if the form rejects it.
4. Wait for the certificate (usually about 15 minutes, up to 24 hours), then repeat the Yahoo redirect URI steps above with the new domain.

A mapping can only point at `/`, not a path like `/fantasy`. Cookies are per host, so users sign in again after the move.

## Deploying from GitHub Actions (optional)

`.github/workflows/deploy-cloud-run.yml` redeploys the app when `src/`, `app/`, `pyproject.toml`, or the workflow itself changes on `main`, and from the Actions tab (Deploy to Cloud Run, then Run workflow). It runs the hermetic app tests first, builds `app/Dockerfile` on the GitHub runner, pushes the image to Artifact Registry tagged with the commit SHA, and swaps it into the existing service with `gcloud run services update --image`, so the secrets, `YAHOO_REDIRECT_URI`, and the memory/CPU/instance settings are left alone. It ends by checking that `/` responds. (It can't use `/healthz`: Cloud Run's front end answers that path itself on `*.run.app` URLs, so it returns a 404 from Google and never reaches the app.)

Docs and test-only merges don't trigger it. A deploy replaces the running instance, so a run in progress is lost and Yahoo users sign in again.

It logs in to Google Cloud with Workload Identity Federation, so no key is stored in GitHub. GitHub proves to Google that the job comes from this repo, and Google lets it act as a deployer service account. One-time setup:

```bash
PROJECT_ID=$(gcloud config get-value project)
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
SA=github-deployer@${PROJECT_ID}.iam.gserviceaccount.com

# 1. The service account the workflow acts as
gcloud iam service-accounts create github-deployer --display-name="GitHub Actions deployer"

# 2. What it may do: update the Cloud Run service, and make API calls against this project
for role in roles/run.admin roles/serviceusage.serviceUsageConsumer; do
  gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:$SA" --role=$role
done

# 3. Push images to the Artifact Registry repo only
gcloud artifacts repositories add-iam-policy-binding fantasyfb --location=us-west1 \
  --member="serviceAccount:$SA" --role=roles/artifactregistry.writer

# 4. Let it deploy a service that runs as the default compute service account
gcloud iam service-accounts add-iam-policy-binding ${PROJECT_NUMBER}-compute@developer.gserviceaccount.com \
  --member="serviceAccount:$SA" --role=roles/iam.serviceAccountUser

# 5. Trust GitHub's identity tokens, but only from this repo
gcloud iam workload-identity-pools create github --location=global --display-name="GitHub Actions"
gcloud iam workload-identity-pools providers create-oidc fantasyfb-repo \
  --location=global --workload-identity-pool=github \
  --issuer-uri=https://token.actions.githubusercontent.com \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='tefirman/fantasyfb'"

# 6. Let identities from that repo act as the service account
gcloud iam service-accounts add-iam-policy-binding $SA \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/attribute.repository/tefirman/fantasyfb"
```

Then give the workflow three repository variables (not secrets, since none is sensitive):

```bash
gh variable set GCP_PROJECT_ID --body "$PROJECT_ID"
gh variable set GCP_SERVICE_ACCOUNT --body "$SA"
gh variable set GCP_WORKLOAD_IDENTITY_PROVIDER \
  --body "projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/providers/fantasyfb-repo"
```

Run the workflow once by hand from the Actions tab to confirm it works. If it fails on a permission, the error names the missing one; add that role to the service account.

The image is built on the runner instead of in Cloud Build, so the service account needs no Cloud Build, logging, or storage roles. An earlier version of this setup used Cloud Build and failed with a bucket "forbidden" error that was hard to trace. If you set that version up, you can remove its extra grants:

```bash
for role in roles/cloudbuild.builds.editor roles/logging.viewer; do
  gcloud projects remove-iam-policy-binding $PROJECT_ID --member="serviceAccount:$SA" --role=$role
done
for role in roles/storage.objectAdmin roles/storage.legacyBucketReader roles/storage.admin; do
  gcloud storage buckets remove-iam-policy-binding gs://${PROJECT_ID}_cloudbuild --member="serviceAccount:$SA" --role=$role
done
```

## Things to expect

- After about 15 idle minutes the instance scales to zero. The next visit takes a few seconds to start, and the first run is slower because the nflverse cache is empty.
- A restart loses sessions and finished reports. Users sign in again.
- A run writes `NewInjuries.csv`/`OldInjuries.csv` to its working directory, so `app/Dockerfile` makes that directory writable by the unprivileged user. Without it every run fails with a `PermissionError`.
- To update, run the build and deploy commands again. The image installs from your local checkout, so commit or not as you like.
- Other settings (`FANTASYFB_RUN_TIMEOUT`, `FANTASYFB_ENABLE_MOVES`, and so on) are listed in `app/README.md` and are passed with `--set-env-vars`.
