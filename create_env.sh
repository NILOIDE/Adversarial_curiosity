#!/bin/bash

module load 2019
module load Anaconda3/2018.12

conda create --name AC pytorch torchvision cudatoolkit=10.1 -c pytorch -y
. /sw/arch/Debian9/EB_production/2019/software/Anaconda3/2018.12/etc/profile.d/conda.sh
conda activate AC

pip install --user -r requirements.txt
pip install pytorch==1.5 -f https://download.pytorch.org/whl/torch_stable.html

# Install atari-py
pip install --no-index -f https://github.com/Kojoley/atari-py/releases atari_py

# Install grid world envs
cd code/grid-gym
pip install -e .
cd ../..