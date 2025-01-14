from __future__ import absolute_import, division, print_function, unicode_literals

import tensorflow as tf

tf.enable_eager_execution()


class BasicBlock(tf.keras.layers.Layer):    # 残差块 building block

    def __init__(self, filters=64, strides=(1, 1)):
        super(BasicBlock, self).__init__()
        self.conv1 = tf.keras.layers.Conv2D(filters, (3, 3), padding='same', strides=strides)
        self.bn1 = tf.keras.layers.BatchNormalization()
        self.relu = tf.keras.layers.ReLU()
        self.conv2 = tf.keras.layers.Conv2D(filters, (3, 3), padding='same')
        self.bn2 = tf.keras.layers.BatchNormalization()
        self.conv3 = tf.keras.layers.Conv2D(filters, (1, 1), padding='same', strides=strides)
        self.bn3 = tf.keras.layers.BatchNormalization()

    def call(self, inputs, training=False):
        x = self.conv1(inputs)
        x = self.bn1(x, training=training)
        x = self.relu(x)
        x = self.conv2(x)
        x = self.bn2(x, training=training)
        if x.shape == inputs.shape:     # 使用1x1卷积处理维度input和res维度不同的情况
            res = inputs
        else:
            res = self.conv3(inputs)
            res = self.bn3(res, training=training)
        x += res        # 残差
        x = self.relu(x)
        return x


class Bottleneck(tf.keras.layers.Layer):    # 残差块   bottleneck design(用两个1x1卷积降低参数数目)

    def __init__(self, filters=64, strides=(1, 1)):
        super(Bottleneck, self).__init__()
        self.conv1 = tf.keras.layers.Conv2D(filters, (1, 1), padding='same', strides=strides)
        self.bn1 = tf.keras.layers.BatchNormalization()
        self.relu = tf.keras.layers.ReLU()
        self.conv2 = tf.keras.layers.Conv2D(filters, (3, 3), padding='same')
        self.bn2 = tf.keras.layers.BatchNormalization()
        self.conv3 = tf.keras.layers.Conv2D(filters * 4, (1, 1), padding='same')
        self.bn3 = tf.keras.layers.BatchNormalization()
        self.conv4 = tf.keras.layers.Conv2D(filters * 4, (1, 1), padding='same', strides=strides)
        self.bn4 = tf.keras.layers.BatchNormalization()

    def call(self, inputs, training=False):
        x = self.conv1(inputs)
        x = self.bn1(x, training=training)
        x = self.relu(x)
        x = self.conv2(x)
        x = self.bn2(x, training=training)
        x = self.relu(x)
        x = self.conv3(x)
        x = self.bn3(x, training=training)
        if x.shape == inputs.shape:
            res = inputs
        else:
            res = self.conv4(inputs)
            res = self.bn4(res, training=training)
        x += res
        x = self.relu(x)
        return x


class ResNet_v1(tf.keras.Model):
    def __init__(self, Block=Bottleneck, layers=(3, 4, 6, 3), include_top=True, embedding_size=512):
        super(ResNet_v1, self).__init__()
        self.conv = tf.keras.layers.Conv2D(64, (7, 7), strides=(2, 2), padding='same')
        self.bn = tf.keras.layers.BatchNormalization()
        self.relu = tf.keras.layers.ReLU()
        self.maxpool = tf.keras.layers.MaxPool2D((3, 3), strides=(2, 2), padding='same')
        self.blocks1 = tf.keras.Sequential([Block(filters=64, strides=(1, 1)) for _ in range(layers[0])])
        self.blocks2 = tf.keras.Sequential(
            [Block(filters=128, strides=(2, 2) if i < 1 else (1, 1)) for i in range(layers[1])])
        self.blocks3 = tf.keras.Sequential(
            [Block(filters=256, strides=(2, 2) if i < 1 else (1, 1)) for i in range(layers[2])])
        self.blocks4 = tf.keras.Sequential(
            [Block(filters=512, strides=(2, 2) if i < 1 else (1, 1)) for i in range(layers[3])])
        self.globalpool = tf.keras.layers.GlobalAveragePooling2D()
        self.dense = None
        if include_top:
            self.dense = tf.keras.layers.Dense(embedding_size)

    def call(self, inputs, training=False, mask=None):
        x = self.conv(inputs)
        x = self.bn(x, training=training)
        x = self.relu(x)
        x = self.maxpool(x)
        x = self.blocks1(x, training=training)  # 可使用中间层
        x = self.blocks2(x, training=training)
        x = self.blocks3(x, training=training)
        x = self.blocks4(x, training=training)
        x = self.globalpool(x)
        if self.dense is not None:
            x = self.dense(x)

        return x


class ResNet_v1_18(ResNet_v1):
    def __init__(self, include_top=True, embedding_size=512):
        super(ResNet_v1_18, self).__init__(Block=BasicBlock, layers=(2, 2, 2, 2), include_top=include_top,
                                           embedding_size=embedding_size)


class ResNet_v1_34(ResNet_v1):
    def __init__(self, include_top=True, embedding_size=512):
        super(ResNet_v1_34, self).__init__(Block=BasicBlock, layers=(3, 4, 6, 3), include_top=include_top,
                                           embedding_size=embedding_size)


class ResNet_v1_50(ResNet_v1):
    def __init__(self, include_top=True, embedding_size=512):
        super(ResNet_v1_50, self).__init__(Block=Bottleneck, layers=(3, 4, 6, 3), include_top=include_top,
                                           embedding_size=embedding_size)


class ResNet_v1_101(ResNet_v1):
    def __init__(self, include_top=True, embedding_size=512):
        super(ResNet_v1_101, self).__init__(Block=Bottleneck, layers=(3, 4, 23, 3), include_top=include_top,
                                            embedding_size=embedding_size)


class ResNet_v1_152(ResNet_v1):
    def __init__(self, include_top=True, embedding_size=512):
        super(ResNet_v1_152, self).__init__(Block=Bottleneck, layers=(3, 8, 36, 3), include_top=include_top,
                                            embedding_size=embedding_size)


def parse_args(argv):
    import argparse
    parser = argparse.ArgumentParser(description='Resnet v1 model.')
    parser.add_argument('--config_path', type=str, help='path to config path', default='../configs/config.yaml')

    args = parser.parse_args(argv)

    return args


def main():
    import sys
    args = parse_args(sys.argv[1:])
    # logger.info(args)
    from recognition.data.generate_data import GenerateData
    import yaml
    with open(args.config_path) as cfg:
        config = yaml.load(cfg, Loader=yaml.FullLoader)
    gd = GenerateData(config)
    train_data, classes = gd.get_train_data()

    model = ResNet_v1_50(embedding_size=config['embedding_size'])
    model.build((None, 112, 112, 3))    # 在自定义layers前执行，指定输入数据的shape
    # model.summary()
    # model = tf.keras.applications.ResNet50(input_shape=(112, 112, 3), include_top=False)
    # model = tf.keras.applications.ResNet50(include_top=True, weights='imagenet')
    # model = tf.keras.applications.ResNet50(include_top=False, input_shape=(224, 224, 3))
    # model.summary()
    # inputs = tf.keras.Input(shape=(112, 112, 3))
    # outputs = ResNet_v1_50(embedding_size=512)(inputs, training=False)
    # model = tf.keras.Model(inputs, outputs)
    # model.summary()
    # tf.keras.utils.plot_model(model, 'my_first_model.png', show_shapes=True)

    for img, _ in train_data.take(1):
        y = model(img, training=False)
        print(img.shape, img[0].shape, y.shape, y)


if __name__ == '__main__':
    # log_cfg_path = '../../logging.yaml'
    # with open(log_cfg_path, 'r') as f:
    #     dict_cfg = yaml.load(f, Loader=yaml.FullLoader)
    # logging.config.dictConfig(dict_cfg)
    # logger = logging.getLogger("mylogger")
    # logger.info("hello, insightface/recognition")
    main()
