from __future__ import absolute_import, division, print_function, unicode_literals

import argparse
import datetime
import os
import platform
import sys
import time

import tensorflow as tf
import yaml

from recognition.backbones.resnet_v1 import ResNet_v1_50
from recognition.data.generate_data import GenerateData
from recognition.losses.loss import arcface_loss, triplet_loss, center_loss
from recognition.models.models import MyModel
from recognition.predict import get_embeddings
from recognition.valid import Valid_Data

# os.environ['CUDA_VISIBLE_DEVICES'] = "2,3"
# config = tf.ConfigProto()
# config.gpu_options.allow_growth = True
# config.gpu_options.per_process_gpu_memory_fraction = 0.4
# tf.enable_eager_execution(config=config)

tf.enable_eager_execution()


# log_cfg_path = '../logging.yaml'
# with open(log_cfg_path, 'r') as f:
#     dict_cfg = yaml.load(f, Loader=yaml.FullLoader)
# logging.config.dictConfig(dict_cfg)
# logger = logging.getLogger("mylogger")

class Trainer:
    def __init__(self, config):
        self.gd = GenerateData(config)

        self.train_data, cat_num = self.gd.get_train_data()
        valid_data = self.gd.get_val_data(config['valid_num'])
        self.model = MyModel(ResNet_v1_50, embedding_size=config['embedding_size'], classes=cat_num)    # 初始化，调用__init__函数
        self.epoch_num = config['epoch_num']
        self.m1 = config['logits_margin1']
        self.m2 = config['logits_margin2']
        self.m3 = config['logits_margin3']
        self.s = config['logits_scale']
        self.alpha = config['alpha']
        self.thresh = config['thresh']
        self.below_fpr = config['below_fpr']
        self.learning_rate = config['learning_rate']
        self.loss_type = config['loss_type']

        # center loss init
        self.centers = None
        self.ct_loss_factor = config['center_loss_factor']
        self.ct_alpha = config['center_alpha']
        if self.loss_type == 'logit' and self.ct_loss_factor > 0:
            self.centers = tf.Variable(initial_value=tf.zeros((cat_num, config['embedding_size'])), trainable=False)

        optimizer = config['optimizer']
        if optimizer == 'ADADELTA':
            self.optimizer = tf.keras.optimizers.Adadelta(self.learning_rate)
        elif optimizer == 'ADAGRAD':
            self.optimizer = tf.keras.optimizers.Adagrad(self.learning_rate)
        elif optimizer == 'ADAM':
            self.optimizer = tf.keras.optimizers.Adam(self.learning_rate)
        elif optimizer == 'ADAMAX':
            self.optimizer = tf.keras.optimizers.Adamax(self.learning_rate)
        elif optimizer == 'FTRL':
            self.optimizer = tf.keras.optimizers.Ftrl(self.learning_rate)
        elif optimizer == 'NADAM':
            self.optimizer = tf.keras.optimizers.Nadam(self.learning_rate)
        elif optimizer == 'RMSPROP':
            self.optimizer = tf.keras.optimizers.RMSprop(self.learning_rate)
        elif optimizer == 'SGD':
            self.optimizer = tf.keras.optimizers.SGD(self.learning_rate)
        else:
            raise ValueError('Invalid optimization algorithm')

        ckpt_dir = os.path.expanduser(config['ckpt_dir'])

        if self.centers is None:
            self.ckpt = tf.train.Checkpoint(backbone=self.model.backbone, model=self.model, optimizer=self.optimizer)
        else:
            # save centers if use center loss
            self.ckpt = tf.train.Checkpoint(backbone=self.model.backbone, model=self.model, optimizer=self.optimizer,
                                            centers=self.centers)
        self.ckpt_manager = tf.train.CheckpointManager(self.ckpt, ckpt_dir, max_to_keep=5, checkpoint_name='mymodel')

        if self.ckpt_manager.latest_checkpoint:
            self.ckpt.restore(self.ckpt_manager.latest_checkpoint)
            print("Restored from {}".format(self.ckpt_manager.latest_checkpoint))
        else:
            print("Initializing from scratch.")

        self.vd = Valid_Data(self.model, valid_data)

        summary_dir = os.path.expanduser(config['summary_dir'])
        current_time = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        train_log_dir = os.path.join(summary_dir, current_time, 'train')
        valid_log_dir = os.path.join(summary_dir, current_time, 'valid')
        # self.graph_log_dir = os.path.join(summary_dir, current_time, 'graph')

        if platform.system() == 'Windows':
            train_log_dir = train_log_dir.replace('/', '\\')
            valid_log_dir = valid_log_dir.replace('/', '\\')
            # self.graph_log_dir = self.graph_log_dir.replace('/', '\\')

        # self.train_summary_writer = tf.summary.create_file_writer(train_log_dir)
        # self.valid_summary_writer = tf.summary.create_file_writer(valid_log_dir)
        self.train_summary_writer = tf.compat.v2.summary.create_file_writer(train_log_dir)
        self.valid_summary_writer = tf.compat.v2.summary.create_file_writer(valid_log_dir)

        # self.graph_writer = tf.compat.v2.summary.create_file_writer(self.graph_log_dir)
        # tf.compat.v2.summary.trace_on(graph=True, profiler=True)
        # with graph_writer.as_default():
        #     tf.compat.v2.summary.trace_export(name="graph_trace", step=0, profiler_outdir=graph_log_dir)

    @tf.function    # 将动态图转为静态图以加快程序运行速度，调试时可注释该局并打印中间变量
    def _train_step(self, img, label):
        with tf.GradientTape(persistent=False) as tape:
            prelogits, dense, norm_dense = self.model(img, training=True)       # 调用call函数

            # sm_loss = softmax_loss(dense, label)
            # norm_sm_loss = softmax_loss(norm_dense, label)
            arc_loss = arcface_loss(prelogits, norm_dense, label, self.m1, self.m2, self.m3, self.s)
            logit_loss = arc_loss

            if self.centers is not None:
                ct_loss, self.centers = center_loss(prelogits, label, self.centers, self.ct_alpha)
            else:
                ct_loss = 0

            loss = logit_loss + self.ct_loss_factor * ct_loss
        gradients = tape.gradient(loss, self.model.trainable_variables)
        self.optimizer.apply_gradients(zip(gradients, self.model.trainable_variables))

        return loss, logit_loss, ct_loss

    @tf.function
    def _train_triplet_step(self, anchor, pos, neg):
        with tf.GradientTape(persistent=False) as tape:
            anchor_emb = get_embeddings(self.model, anchor)
            pos_emb = get_embeddings(self.model, pos)
            neg_emb = get_embeddings(self.model, neg)

            loss = triplet_loss(anchor_emb, pos_emb, neg_emb, self.alpha)

        gradients = tape.gradient(loss, self.model.trainable_variables)
        self.optimizer.apply_gradients(zip(gradients, self.model.trainable_variables))

        return loss

    def train(self):
        for epoch in range(self.epoch_num):
            start = time.time()
            # triplet loss
            if self.loss_type == 'triplet':
                train_data, num_triplets = self.gd.get_train_triplets_data(self.model)
                print('triplets num is {}'.format(num_triplets))
                if num_triplets > 0:
                    for step, (anchor, pos, neg) in enumerate(train_data):
                        loss = self._train_triplet_step(anchor, pos, neg)
                        with self.train_summary_writer.as_default():
                            tf.compat.v2.summary.scalar('loss', loss, step=step)
                        print('epoch: {}, step: {}, loss = {}'.format(epoch, step, loss))
            elif self.loss_type == 'logit':
                # logit loss
                for step, (input_image, target) in enumerate(self.train_data):
                    loss, logit_loss, ct_loss = self._train_step(input_image, target)
                    with self.train_summary_writer.as_default():
                        tf.compat.v2.summary.scalar('loss', loss, step=step)
                        tf.compat.v2.summary.scalar('logit_loss', logit_loss, step=step)
                        tf.compat.v2.summary.scalar('center_loss', ct_loss, step=step)
                    print('epoch: {}, step: {}, loss = {}, logit_loss = {}, center_loss = {}'.format(epoch, step, loss,
                                                                                                     logit_loss,
                                                                                                     ct_loss))
            else:
                raise ValueError('Invalid loss type')

            # valid
            acc, p, r, fpr, acc_fpr, p_fpr, r_fpr, thresh_fpr = self.vd.get_metric(self.thresh, self.below_fpr)

            with self.valid_summary_writer.as_default():
                tf.compat.v2.summary.scalar('acc', acc, step=epoch)
                tf.compat.v2.summary.scalar('p', p, step=epoch)
                tf.compat.v2.summary.scalar('r=tpr', r, step=epoch)
                tf.compat.v2.summary.scalar('fpr', fpr, step=epoch)
                tf.compat.v2.summary.scalar('acc_fpr', acc_fpr, step=epoch)
                tf.compat.v2.summary.scalar('p_fpr', p_fpr, step=epoch)
                tf.compat.v2.summary.scalar('r=tpr_fpr', r_fpr, step=epoch)
                tf.compat.v2.summary.scalar('thresh_fpr', thresh_fpr, step=epoch)
            print('epoch: {}, acc: {:.3f}, p: {:.3f}, r=tpr: {:.3f}, fpr: {:.3f} \n'
                  'fix fpr <= {}, acc: {:.3f}, p: {:.3f}, r=tpr: {:.3f}, thresh: {:.3f}'
                  .format(epoch, acc, p, r, fpr, self.below_fpr, acc_fpr, p_fpr, r_fpr, thresh_fpr))

            # ckpt
            # if epoch % 5 == 0:
            save_path = self.ckpt_manager.save()
            print('Saving checkpoint for epoch {} at {}'.format(epoch, save_path))

            print('Time taken for epoch {} is {} sec\n'.format(epoch, time.time() - start))


def parse_args(argv):
    parser = argparse.ArgumentParser(description='Train face network')
    parser.add_argument('--config_path', type=str, help='path to config path', default='configs/config.yaml')

    args = parser.parse_args(argv)

    return args


def main():
    args = parse_args(sys.argv[1:])
    # logger.info(args)

    with open(args.config_path) as cfg:
        config = yaml.load(cfg, Loader=yaml.FullLoader)

    t = Trainer(config)
    t.train()


if __name__ == '__main__':
    # logger.info("hello, insightface/recognition")
    main()
