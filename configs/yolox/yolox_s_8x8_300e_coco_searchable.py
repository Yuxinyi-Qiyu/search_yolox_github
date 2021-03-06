_base_ = [
    '../_base_/schedules/schedule_1x.py',
    '../_base_/default_runtime.py'
]
# checkpoint_config = dict(interval=interval)
# todo: search_head等参数，按照学姐cfg文件格式改！
checkpoint_config = dict(type='CheckpointHook_nolog', interval=1)
primitives = [
            'conv1x1', 'conv3x3', 'conv5x5'
        ]
# panas_c_range = [16, 64]
# widen_factor_range = [0, 1.0]
widen_factor_range = [0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0]
widen_factor = [1.0, 1.0, 1.0, 1.0, 1.0] # 每个stage的factor,最后一个表示stage4的outchannel
deepen_factor_range = [0.33, 1.0]
search_backbone = True
search_neck = True
search_head = False
img_scale = (640, 640)
panas_type = len(primitives)
panas_c_range = [64, 256]
panas_d_range = [1, 5]
head_d_range = [1, 3]
cb_step = 2
cb_type = 1
init_c = panas_c_range[1] + 16


runner = dict(type='EpochBasedRunnerSuper', max_epochs=300,
              panas_c_range=panas_c_range,
              widen_factor_range=widen_factor_range,
              deepen_factor_range=deepen_factor_range,
              search_backbone=search_backbone,
              search_neck=search_neck,
              search_head=search_head
              )
# runner = dict(type='EpochBasedRunner', max_epochs=max_epochs)
# log_config = dict(
#     interval=50,
#     hooks=[
#         dict(type='TextLoggerHook'),
#         # dict(type='TensorboardLoggerHook')
#     ])
find_unused_parameters=True




optimizer = dict(
    type='SGD',
    lr=0.01,
    momentum=0.9,
    weight_decay=5e-4,
    nesterov=True,
    paramwise_cfg=dict(norm_decay_mult=0., bias_decay_mult=0.))
# optimizer_config = dict(type='OptimizerHookSuper', _delete_=True, grad_clip=dict(max_norm=35, norm_type=2)) # 是啥
optimizer_config = dict(grad_clip=None)



# model settings
model = dict(
    type='YOLOX_Searchable',
    input_size=img_scale,
    random_size_range=(15, 25),
    random_size_interval=10,
    backbone=dict(
        type='CSPDarknet_Searchable',
        conv_cfg=dict(type='USConv2d'),
        # norm_cfg=dict(type='BN', momentum=0.03, eps=0.001),
        norm_cfg=dict(type='USBN2d'), # dict(type='BN', momentum=0.03, eps=0.001),
        # deepen_factor=0.33,
        deepen_factor=[1.0, 1.0, 1.0, 1.0],
        # widen_factor=0.5,
        # widen_factor=1.0,
        widen_factor=widen_factor),
    neck=dict(
        type='YOLOXPAFPN_Searchable',
        conv_cfg=dict(type='USConv2d'),
        norm_cfg=dict(type='USBN2d'),
        # in_channels=[128, 256, 512],
        in_channels=[256, 512, 1024],
        # out_channels=128,
        out_channels=256,
        num_csp_blocks=1),
    bbox_head=dict(
        type='YOLOXHead', num_classes=80, in_channels=256, feat_channels=256), # feat_channels 是啥
    train_cfg=dict(assigner=dict(type='SimOTAAssigner', center_radius=2.5)),
    # In order to align the source code, the threshold of the val phase is
    # 0.01, and the threshold of the test phase is 0.001.
    test_cfg=dict(score_thr=0.01, nms=dict(type='nms', iou_threshold=0.65)))

# dataset settings
data_root = 'data/coco/'
dataset_type = 'CocoDataset'
# data_root = 'data/VOCdevkit/'
# dataset_type = 'VOCDataset'

train_pipeline = [
    dict(type='Mosaic', img_scale=img_scale, pad_val=114.0),
    dict(
        type='RandomAffine',
        scaling_ratio_range=(0.1, 2),
        border=(-img_scale[0] // 2, -img_scale[1] // 2)),
    dict(
        type='MixUp',
        img_scale=img_scale,
        ratio_range=(0.8, 1.6),
        pad_val=114.0),
    dict(type='YOLOXHSVRandomAug'),
    dict(type='RandomFlip', flip_ratio=0.5),
    # According to the official implementation, multi-scale
    # training is not considered here but in the
    # 'mmdet/models/detectors/yolox.py'.
    dict(type='Resize', img_scale=img_scale, keep_ratio=True),
    dict(
        type='Pad',
        pad_to_square=True,
        # If the image is three-channel, the pad value needs
        # to be set separately for each channel.
        pad_val=dict(img=(114.0, 114.0, 114.0))),
    dict(type='FilterAnnotations', min_gt_bbox_wh=(1, 1), keep_empty=False),
    dict(type='DefaultFormatBundle'),
    dict(type='Collect', keys=['img', 'gt_bboxes', 'gt_labels'])
]

train_dataset = dict(
    type='MultiImageMixDataset',
    dataset=dict(
        type=dataset_type,
        # ann_file=data_root + 'annotations/instances_val2017.json',
        # ann_file=data_root + 'annotations/0.01minival.json',
        # img_prefix=data_root + 'val2017/',
        ann_file=data_root + 'annotations/instances_train2017.json',
        img_prefix=data_root + 'train2017/',
        pipeline=[
            dict(type='LoadImageFromFile'),
            dict(type='LoadAnnotations', with_bbox=True)
        ],
        filter_empty_gt=False,
    ),
    pipeline=train_pipeline)

test_pipeline = [
    dict(type='LoadImageFromFile'),
    dict(
        type='MultiScaleFlipAug',
        img_scale=img_scale,
        flip=False,
        transforms=[
            dict(type='Resize', keep_ratio=True),
            dict(type='RandomFlip'),
            dict(
                type='Pad',
                pad_to_square=True,
                pad_val=dict(img=(114.0, 114.0, 114.0))),
            dict(type='DefaultFormatBundle'),
            dict(type='Collect', keys=['img'])
        ])
]

data = dict(
    samples_per_gpu=8, # 8张卡；2张卡是32
    # samples_per_gpu=16, # 8张卡；2张卡是32
    workers_per_gpu=4,
    persistent_workers=True,
    train=train_dataset,
    val=dict(
        type=dataset_type,
        # ann_file=data_root + 'annotations/0.01minival.json',
        ann_file=data_root + 'annotations/instances_val2017.json',
        img_prefix=data_root + 'val2017/',
        pipeline=test_pipeline),
    test=dict(
        type=dataset_type,
        # ann_file=data_root + 'annotations/0.01minival.json',
        ann_file=data_root + 'annotations/instances_val2017.json',
        img_prefix=data_root + 'val2017/',
        pipeline=test_pipeline))



max_epochs = 300
num_last_epochs = 15
resume_from = None
interval = 10

# learning policy
lr_config = dict(
    _delete_=True,
    policy='YOLOX',
    warmup='exp',
    by_epoch=False,
    warmup_by_epoch=True,
    warmup_ratio=1,
    warmup_iters=5,  # 5 epoch
    num_last_epochs=num_last_epochs,
    min_lr_ratio=0.05)



custom_hooks = [
    dict(
        type='YOLOXModeSwitchHook',
        num_last_epochs=num_last_epochs,
        priority=48),
    dict(
        type='SyncNormHook',
        num_last_epochs=num_last_epochs,
        interval=interval,
        priority=48),
    dict(
        type='ExpMomentumEMAHook',
        resume_from=resume_from,
        momentum=0.0001,
        priority=49)
]

evaluation = dict(
    save_best='auto',
    # The evaluation interval is 'interval' when running epoch is
    # less than ‘max_epochs - num_last_epochs’.
    # The evaluation interval is 1 when running epoch is greater than
    # or equal to ‘max_epochs - num_last_epochs’.
    # interval=interval,
    interval=10,
    # dynamic_intervals=[(max_epochs - num_last_epochs, 1)],
    metric='bbox')

log_config = dict(interval=50)

