# Copyright (c) Open-MMLab. All rights reserved.
import os.path as osp
import platform
import shutil
import time
import warnings

import torch

import mmcv
from mmcv.runner import EpochBasedRunner, save_checkpoint, get_host_info, RUNNERS
import numpy as np
from random import choice
import random

torch.manual_seed(0)
torch.cuda.manual_seed_all(0)
np.random.seed(0)
random.seed(0)


@RUNNERS.register_module()
class EpochBasedRunner_tfs(EpochBasedRunner):
    """Epoch-based Runner.

    This runner train models epoch by epoch.
    """

    def __init__(self,
                 panas_type=0,
                 panas_c_range=[128, 256],
                 panas_d_range=[3, 12],
                 head_d_range=[1, 3],
                 widen_factor_range=[0, 1],
                 deepen_factor_range=[0, 1],
                 cb_type=3,
                 cb_step=4,
                 c_interval=16,
                 w_interval=16,  # @todo
                 base_channel=64,
                 search_backbone=True,
                 search_neck=True,
                 search_head=False,
                 sandwich=False,
                 **kwargs):
        self.panas_type = panas_type
        self.step = 0
        self.panas_c_range = panas_c_range
        self.panas_d_range = panas_d_range
        self.head_d_range = head_d_range
        self.widen_factor_range = widen_factor_range,
        self.deepen_factor_range = deepen_factor_range,
        self.cb_type = cb_type
        self.cb_step = cb_step
        self.c_interval = c_interval
        self.base_channel = base_channel
        self.w_interval = w_interval
        self.sandwich = sandwich

        self.search_backbone = search_backbone
        self.search_neck = search_neck
        self.search_head = search_head

        self.arch = None

        super(EpochBasedRunner_tfs, self).__init__(**kwargs)

    def run_iter(self, data_batch, train_mode, **kwargs):
        if self.batch_processor is not None:
            outputs = self.batch_processor(
                self.model, data_batch, train_mode=train_mode, **kwargs)
        elif train_mode:

            outputs = self.model.train_step(data_batch, self.optimizer,
                                            **kwargs)
        else:
            outputs = self.model.val_step(data_batch, self.optimizer, **kwargs)
        if not isinstance(outputs, dict):
            raise TypeError('"batch_processor()" or "model.train_step()"'
                            'and "model.val_step()" must return a dict')

        if 'log_vars' in outputs:
            self.log_buffer.update(outputs['log_vars'], outputs['num_samples'])
        self.outputs = outputs

    def get_cand_arch(self, max_arch=False, min_arch=False):
        arch = {}
        if self.search_backbone:
            widen_factor_range = self.widen_factor_range[0]  # todo ??  ([0,1],)
            deepen_factor_range = self.deepen_factor_range[0]  # todo??
            # todo: arch['widen_factor'] = np.random.uniform(widen_factor_range[0], widen_factor_range[1]) * self.base_channel // self.w_interval * self.w_interval #[0,1]
            arch['widen_factor'] = []
            arch['deepen_factor'] = []
            for i in range(5):
                arch['widen_factor'].append(
                    widen_factor_range[np.random.randint(0, len(widen_factor_range))])  # todo [0,1]
                # arch['widen_factor'].append(np.random.uniform(widen_factor_range[0]+0.001, widen_factor_range[1]+0.001)) #todo [0,1]
            for i in range(4):
                arch['deepen_factor'].append(deepen_factor_range[np.random.randint(0, len(deepen_factor_range))])
            # print("arch['widen_factor']:"+str(arch['widen_factor']))
            # print("arch['deepen_factor']:"+str(arch['deepen_factor']))
            # todo: deepen是随机生成数组下标，要改
        # if self.search_neck:
        #     arch['panas_arch'] = [np.random.randint(self.panas_type) for i in range(self.panas_d_range[1])]
        #     arch['panas_d'] = np.random.randint(self.panas_d_range[0], self.panas_d_range[1] + 1)
        #     arch['panas_d'] = self.panas_d_range[1]
        #     arch['panas_c'] = np.random.randint(self.panas_c_range[0], self.panas_c_range[
        #         1] + self.c_interval) // self.c_interval * self.c_interval # 随机取base-channel，并保证是16的倍数

        # if self.search_head:
        #     if self.head_d_range:
        #         # arch['head_step'] = self.head_d_range[1]
        #         arch['head_step'] = np.random.randint(self.head_d_range[0], self.head_d_range[1] + 1)
        #         if max_arch:
        #             arch['head_step'] = self.head_d_range[1]
        #         if min_arch:
        #             arch['head_step'] = self.head_d_range[0]
        #     else:
        #         arch['head_step'] = 1

        return arch

    def set_grad_none(self, **kwargs):
        self.model.module.set_grad_none(**kwargs)

    def train(self, data_loader, **kwargs):
        self.model.train()
        self.mode = 'train'
        self.data_loader = data_loader
        self._max_iters = self._max_epochs * len(self.data_loader)
        self.call_hook('before_train_epoch')
        time.sleep(2)  # Prevent possible deadlock during epoch transition

        for i, data_batch in enumerate(self.data_loader):
            self._inner_iter = i
            self.call_hook('before_train_iter')
            self.arch = self.get_cand_arch()

            if self.sandwich:  # false
                self.archs = []
                self.archs.append(self.get_cand_arch(max_arch=True))
                self.archs.append(self.get_cand_arch(min_arch=True))
                self.archs.append(self.get_cand_arch())
                self.archs.append(self.arch)
                self.model.module.set_archs(self.archs, **kwargs)
            # else:
            #     self.model.module.set_arch(self.arch, **kwargs)

            # self.logger.info(f'arch: {self.arch}')
            self.run_iter(data_batch, train_mode=True, **kwargs)
            self.call_hook('after_train_iter')
            self._iter += 1

        self.call_hook('after_train_epoch')
        self._epoch += 1

