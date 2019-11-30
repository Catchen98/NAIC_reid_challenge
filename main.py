import sys
import os
import os.path as osp
import warnings
import time
import argparse
import torch
import torch.nn as nn

from data import ImageDataManager
from models import build_model
from engine import ImageSoftmaxEngine, ImageTripletEngine, InfenerceEngine, ImageCenterEngine, ImageOHEMEngine
from default_config import (
    get_default_config, imagedata_kwargs,
    optimizer_kwargs, lr_scheduler_kwargs, engine_run_kwargs
)
from optim import build_optimizer, build_lr_scheduler

from utils import (
    Logger, set_random_seed, check_isfile, resume_from_checkpoint,
    load_pretrained_weights, compute_model_complexity, collect_env_info
)


def build_datamanager(cfg):
    return ImageDataManager(**imagedata_kwargs(cfg))


def build_engine(cfg, datamanager, model, optimizer, scheduler):
    if cfg.data.is_train:
        if cfg.loss.name == 'softmax':
            engine = ImageSoftmaxEngine(
                datamanager,
                model,
                optimizer,
                scheduler=scheduler,
                use_gpu=cfg.use_gpu,
                label_smooth=cfg.loss.softmax.label_smooth
            )
        elif cfg.loss.name == 'triplet':
            engine = ImageTripletEngine(
                datamanager,
                model,
                optimizer,
                margin=cfg.loss.triplet.margin,
                weight_t=cfg.loss.triplet.weight_t,
                weight_x=cfg.loss.triplet.weight_x,
                scheduler=scheduler,
                use_gpu=cfg.use_gpu,
                metric=cfg.loss.triplet.metric,
                label_smooth=cfg.loss.softmax.label_smooth,
                ranked_loss=cfg.loss.triplet.ranked_loss,
                ms_loss=cfg.loss.triplet.ms_loss
            )
        elif cfg.loss.name == 'center':
            engine = ImageCenterEngine(
                datamanager,
                model,
                optimizer,
                margin=cfg.loss.triplet.margin,
                weight_t=cfg.loss.center.weight_t,
                weight_x=cfg.loss.center.weight_x,
                weight_c=cfg.loss.center.weight_c,
                scheduler=scheduler,
                use_gpu=cfg.use_gpu,
                metric=cfg.loss.triplet.metric,
                feature_dim=cfg.loss.center.feature_dim,
                label_smooth=cfg.loss.softmax.label_smooth,
                num_features=cfg.loss.center.num_features,
            )
        elif cfg.loss.name == 'ohem':
            engine = ImageOHEMEngine(
                datamanager,
                model,
                optimizer,
                margin=cfg.loss.triplet.margin,
                weight_t=cfg.loss.ohem.weight_t,
                weight_x=cfg.loss.ohem.weight_x,
                weight_f=cfg.loss.ohem.weight_f,
                scheduler=scheduler,
                use_gpu=cfg.use_gpu,
                metric=cfg.loss.triplet.metric,
                label_smooth=cfg.loss.softmax.label_smooth
            )
    # inference
    else:
        engine = InfenerceEngine(
            datamanager,
            model,
            use_gpu=cfg.use_gpu,
        )
    return engine


def reset_config(cfg, args):
    if args.root:
        cfg.data.root = args.root
    if args.sources:
        cfg.data.sources = args.sources
    if args.targets:
        cfg.data.targets = args.targets
    if args.transforms:
        cfg.data.transforms = args.transforms


def main():
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--config_file', type=str, default='', help='path to config file')
    parser.add_argument('-s', '--sources', type=str, nargs='+', help='source datasets (delimited by space)')
    parser.add_argument('-t', '--targets', type=str, nargs='+', help='target datasets (delimited by space)')
    parser.add_argument('--transforms', type=str, nargs='+', help='data augmentation')
    parser.add_argument('--root', type=str, default='', help='path to data root')
    parser.add_argument('opts', default=None, nargs=argparse.REMAINDER,
                        help='Modify config options using the command-line')
    args = parser.parse_args()

    cfg = get_default_config()
    cfg.use_gpu = torch.cuda.is_available()
    if args.config_file:
        cfg.merge_from_file(args.config_file)
    reset_config(cfg, args)
    cfg.merge_from_list(args.opts)
    set_random_seed(cfg.train.seed)

    log_name = 'test.log' if cfg.test.evaluate else 'train.log'
    log_name += time.strftime('-%Y-%m-%d-%H-%M-%S')
    sys.stdout = Logger(osp.join(cfg.data.save_dir, log_name))

    print('Show configuration\n{}\n'.format(cfg))
    print('Collecting env info ...')
    print('** System info **\n{}\n'.format(collect_env_info()))

    datamanager = build_datamanager(cfg)

    print('Building model: {}'.format(cfg.model.name))
    model = build_model(
        name=cfg.model.name,
        num_classes=datamanager.num_train_pids,
        loss=cfg.loss.name,
        pretrained=cfg.model.pretrained,
        use_gpu=cfg.use_gpu
    )
    # num_params, flops = compute_model_complexity(model, (1, 3, cfg.data.height, cfg.data.width))
    # print('Model complexity: params={:,} flops={:,}'.format(num_params, flops))

    if cfg.model.load_weights and check_isfile(cfg.model.load_weights):
        load_pretrained_weights(model, cfg.model.load_weights)

    if cfg.use_gpu:
        model = nn.DataParallel(model).cuda()

    optimizer = build_optimizer(model, **optimizer_kwargs(cfg))
    scheduler = build_lr_scheduler(optimizer, **lr_scheduler_kwargs(cfg))

    if cfg.model.resume and check_isfile(cfg.model.resume):
        cfg.train.start_epoch = resume_from_checkpoint(cfg.model.resume, model, optimizer=optimizer)

    print('Building {}-engine for {}-reid'.format(cfg.loss.name, cfg.data.type))
    engine = build_engine(cfg, datamanager, model, optimizer, scheduler)
    engine.run(**engine_run_kwargs(cfg))


if __name__ == '__main__':
    main()