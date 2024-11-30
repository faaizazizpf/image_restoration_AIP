import argparse
import logging
import os.path
import sys
import time
from collections import OrderedDict
import torchvision.utils as tvutils

import numpy as np
import torch
from IPython import embed
import lpips

import options as option
from models import create_model

sys.path.insert(0, "../../")
import utils as util
from data import create_dataloader, create_dataset
from data.util import bgr2ycbcr

#### options
parser = argparse.ArgumentParser()
parser.add_argument("-opt", type=str, required=True, help="Path to options YMAL file.")
opt = option.parse(parser.parse_args().opt, is_train=False)

opt = option.dict_to_nonedict(opt)

#### mkdir and logger
util.mkdirs(
    (
        path
        for key, path in opt["path"].items()
        if not key == "experiments_root"
        and "pretrain_model" not in key
        and "resume" not in key
    )
)

os.system("rm ./result")
os.symlink(os.path.join(opt["path"]["results_root"], ".."), "./result")

util.setup_logger(
    "base",
    opt["path"]["log"],
    "test_" + opt["name"],
    level=logging.INFO,
    screen=True,
    tofile=True,
)
logger = logging.getLogger("base")
logger.info(option.dict2str(opt))

#### Create test dataset and dataloader
test_loaders = []
for phase, dataset_opt in sorted(opt["datasets"].items()):
    test_set = create_dataset(dataset_opt)
    test_loader = create_dataloader(test_set, dataset_opt)
    logger.info(
        "Number of test images in [{:s}]: {:d}".format(
            dataset_opt["name"], len(test_set)
        )
    )
    test_loaders.append(test_loader)

# load pretrained model by default
model = create_model(opt)
device = model.device

sde = util.IRSDE(max_sigma=opt["sde"]["max_sigma"], T=opt["sde"]["T"], schedule=opt["sde"]["schedule"], eps=opt["sde"]["eps"], device=device)
sde.set_model(model.model)

scale = opt['degradation']['scale']

for test_loader in test_loaders:
    test_set_name = test_loader.dataset.opt["name"]  # path opt['']
    logger.info("\nTesting [{:s}]...".format(test_set_name))
    test_start_time = time.time()
    dataset_dir = os.path.join(opt["path"]["results_root"], test_set_name)
    util.mkdir(dataset_dir)

    test_times = []

    for i, test_data in enumerate(test_loader):
        need_GT = False if test_loader.dataset.opt["dataroot_GT"] is None else True
        img_path = test_data["GT_path"][0] if need_GT else test_data["LQ_path"][0]
        img_name = os.path.splitext(os.path.basename(img_path))[0]
        print(img_name)

        #if i < 37:
        #    continue

        #### input dataset_LQ
        LQ = test_data["LQ"]
        LQ_L, LQ_R = LQ.chunk(2, dim=1)
        LQ_L = util.upscale(LQ_L, scale=4)
        LQ_R = util.upscale(LQ_R, scale=4)
        LQ = torch.cat([LQ_L, LQ_R], dim=1)
        noisy_state = sde.noise_state(LQ)

        model.feed_data(noisy_state, LQ)
        tic = time.time()
        model.test(sde, save_states=False)
        toc = time.time()
        test_times.append(toc - tic)

        visuals = model.get_current_visuals(need_GT=False)
        SR_img = visuals["Output"]
        SR_imgL, SR_imgR = SR_img.chunk(2, dim=0)
        outputL = util.tensor2img(SR_imgL.squeeze())  # uint8
        outputR = util.tensor2img(SR_imgR.squeeze())  # uint8
        
        suffix = opt["suffix"]
        if suffix:
            save_imgL_path = os.path.join(dataset_dir, img_name + suffix + ".png")
            save_imgR_path = os.path.join(dataset_dir, img_name.replace('L', 'R') + suffix + ".png")
        else:
            save_imgL_path = os.path.join(dataset_dir, img_name + ".png")
            save_imgR_path = os.path.join(dataset_dir, img_name.replace('L', 'R') + ".png")
        util.save_img(outputL, save_imgL_path)
        util.save_img(outputR, save_imgR_path)

    print(f"average test time: {np.mean(test_times):.4f}")

