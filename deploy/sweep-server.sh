#!/bin/bash
#SBATCH --job-name=sweep_server
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=3-00:00:00
#SBATCH --output="/scratch/wlp9800/logs/%x-%j.out"
#SBATCH --error="/scratch/wlp9800/logs/%x-%j.err"

source ~/.secrets/env.sh

sed -i '/^export SWEEP_HOST=/d' ~/.secrets/env.sh
echo "export SWEEP_HOST=$(hostname)" >> ~/.secrets/env.sh

singularity run --containall --cleanenv \
    --env DB_HOST="$DB_HOST" \
    --env DB_PORT="$PGPORT" \
    --env DB_NAME="$POSTGRES_DB" \
    --env DB_USER="$POSTGRES_USER" \
    --env DB_PASSWORD="$POSTGRES_PASSWORD" \
    --env PORT="$SWEEP_PORT" \
    docker://thewillyp/sweep-server:main-14
