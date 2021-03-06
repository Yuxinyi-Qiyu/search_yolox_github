# Copyright (c) OpenMMLab. All rights reserved.
import random

import torch
import torch.distributed as dist
import torch.nn.functional as F
from mmcv.runner import get_dist_info

from ..builder import DETECTORS
from .single_stage import SingleStageDetector
from .kd_loss import *

@DETECTORS.register_module()
class YOLOX_Searchable_Sandwich(SingleStageDetector):
    r"""Implementation of `YOLOX: Exceeding YOLO Series in 2021
    <https://arxiv.org/abs/2107.08430>`_

    Note: Considering the trade-off between training speed and accuracy,
    multi-scale training is temporarily kept. More elegant implementation
    will be adopted in the future.

    Args:
        backbone (nn.Module): The backbone module.
        neck (nn.Module): The neck module.
        bbox_head (nn.Module): The bbox head module.
        train_cfg (obj:`ConfigDict`, optional): The training config
            of YOLOX. Default: None.
        test_cfg (obj:`ConfigDict`, optional): The testing config
            of YOLOX. Default: None.
        pretrained (str, optional): model pretrained path.
            Default: None.
        input_size (tuple): The model default input image size.
            Default: (640, 640).
        size_multiplier (int): Image size multiplication factor.
            Default: 32.
        random_size_range (tuple): The multi-scale random range during
            multi-scale training. The real training image size will
            be multiplied by size_multiplier. Default: (15, 25).
        random_size_interval (int): The iter interval of change
            image size. Default: 10.
        init_cfg (dict, optional): Initialization config dict.
            Default: None.
    """

    def __init__(self,
                 backbone,
                 neck,
                 bbox_head,
                 train_cfg=None,
                 test_cfg=None,
                 pretrained=None,
                 input_size=(640, 640),
                 size_multiplier=32,
                 random_size_range=(15, 25),
                 random_size_interval=10,
                 init_cfg=None,
                 search_backbone=True,
                 search_neck=True,
                 search_head=False,
                 sandwich=False,
                 inplace=False, # distill
                 kd_weight=1e-8, # 1e-3
                 ):
        super(YOLOX_Searchable_Sandwich, self).__init__(
            backbone,
            neck,
            bbox_head,
            train_cfg,
            test_cfg,
            pretrained,
            init_cfg,
        )

        self.rank, self.world_size = get_dist_info()
        self._default_input_size = input_size
        self._input_size = input_size
        self._random_size_range = random_size_range
        self._random_size_interval = random_size_interval
        self._size_multiplier = size_multiplier
        self._progress_in_iter = 0
        self.search_backbone = search_backbone
        self.search_neck = search_neck
        self.search_head = search_head
        self.sandwich = sandwich
        self.inplace = inplace
        self.arch = None
        self.archs = None
        self.out_channels = self.neck.out_channels
        self.kd_weight = kd_weight
        # ?????????????????????loss????????????
        if self.inplace == 'L2':
            self.kd_loss = DL2()
        elif self.inplace == 'L2Softmax':
            self.kd_loss = DL2(softmax=True)
        elif self.inplace == 'DML':
            self.kd_loss = DML()
        elif self.inplace == 'NonLocal':
            self.kd_loss = NonLocalBlockLoss(self.out_channels, 64)
        # self.set_arch({'panas_arch': (3, 3, 1, 2, -1), 'panas_c': 112, 'panas_d': 4, 'cb_type': 0, 'cb_step': 2, 'head_step': 2})

    def set_archs(self, archs, **kwargs):
        self.archs = archs

    def set_arch(self, arch, **kwargs):
        self.arch = arch
        if self.search_backbone:
            self.backbone.set_arch(self.arch)
            self.neck.set_arch(self.arch)
        if self.search_neck:
            self.bbox_head.set_arch(self.arch)
        # if self.search_head:

    def extract_feat(self, img):
        """Directly extract features from the backbone+neck."""
        x = self.backbone(img) # len(x) 3
        input_neck = []
        for stage_out in x:
            input_neck.append(stage_out)
        x = self.neck(input_neck)
        # x = self.neck([x[0],x[1],x[2]])
        return x #tuple (tensor) len=3

    def forward_train(self,
                      img,
                      img_metas,
                      gt_bboxes,
                      gt_labels,
                      gt_bboxes_ignore=None):
        """
        Args:
            img (Tensor): Input images of shape (N, C, H, W).
                Typically these should be mean centered and std scaled.
            img_metas (list[dict]): A List of image info dict where each dict
                has: 'img_shape', 'scale_factor', 'flip', and may also contain
                'filename', 'ori_shape', 'pad_shape', and 'img_norm_cfg'.
                For details on the values of these keys see
                :class:`mmdet.datasets.pipelines.Collect`.
            gt_bboxes (list[Tensor]): Each item are the truth boxes for each
                image in [tl_x, tl_y, br_x, br_y] format.
            gt_labels (list[Tensor]): Class indices corresponding to each box
            gt_bboxes_ignore (None | list[Tensor]): Specify which bounding
                boxes can be ignored when computing the loss.
        Returns:
            dict[str, Tensor]: A dictionary of loss components.
        """
        # Multi-scale training
        img, gt_bboxes = self._preprocess(img, gt_bboxes)

        losses = dict()
        if not isinstance(self.archs, list): # not sandwich
            self.archs = [self.arch]

        for idx, arch in enumerate(self.archs):
            if self.search_backbone or self.search_neck:
                self.set_arch(arch)

            # x = self.extract_feat(img)
            x = self.backbone(img)
            x = self.neck(x)

            if len(self.archs) > 1 and self.inplace: # inplace distill
                if idx == 0: # ???????????????
                    teacher_feat = x
                else:
                    kd_feat_loss = 0
                    student_feat = x
                    for i in range(len(student_feat)):
                        kd_feat_loss += self.kd_loss(student_feat[i], teacher_feat[i].detach(), i) * self.kd_weight

                    losses.update({'kd_feat_loss_{}'.format(idx): kd_feat_loss})

            head_loss = self.bbox_head.forward_train(x, img_metas, gt_bboxes,
                                              gt_labels, gt_bboxes_ignore)

            losses.update({'loss_cls_{}'.format(idx): head_loss['loss_cls']})
            losses.update({'loss_bbox_{}'.format(idx): head_loss['loss_bbox']})
            losses.update({'loss_obj_{}'.format(idx): head_loss['loss_obj']})

        # random resizing
        if (self._progress_in_iter + 1) % self._random_size_interval == 0:
            self._input_size = self._random_resize()
        self._progress_in_iter += 1

        return losses

    def _preprocess(self, img, gt_bboxes):
        scale_y = self._input_size[0] / self._default_input_size[0]
        scale_x = self._input_size[1] / self._default_input_size[1]
        if scale_x != 1 or scale_y != 1:
            img = F.interpolate(
                img,
                size=self._input_size,
                mode='bilinear',
                align_corners=False)
            for gt_bbox in gt_bboxes:
                gt_bbox[..., 0::2] = gt_bbox[..., 0::2] * scale_x
                gt_bbox[..., 1::2] = gt_bbox[..., 1::2] * scale_y
        return img, gt_bboxes

    def _random_resize(self):
        tensor = torch.LongTensor(2).cuda()

        if self.rank == 0:
            size = random.randint(*self._random_size_range)
            aspect_ratio = float(
                self._default_input_size[1]) / self._default_input_size[0]
            size = (self._size_multiplier * size,
                    self._size_multiplier * int(aspect_ratio * size))
            tensor[0] = size[0]
            tensor[1] = size[1]

        if self.world_size > 1:
            dist.barrier()
            dist.broadcast(tensor, 0)

        input_size = (tensor[0].item(), tensor[1].item())
        return input_size
