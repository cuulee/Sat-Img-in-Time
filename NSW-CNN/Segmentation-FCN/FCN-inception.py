# encoding: utf-8

# setting environments
import sys
import os
from optparse import OptionParser

parser = OptionParser()
parser.add_option("--save", dest="save_path")
parser.add_option("--name", dest="model_name")
parser.add_option("--record_summary", action="store_true", default=False, dest="record_summary")

parser.add_option("--train", dest="path_train_set", default="../../Data/090085/Road_Data/motor_trunk_pri_sec_tert_uncl_track/posneg_seg_coord_split_thr1_128_16_train")
parser.add_option("--cv", dest="path_cv_set", default="../../Data/090085/Road_Data/motor_trunk_pri_sec_tert_uncl_track/posneg_seg_coord_split_thr1_128_16_cv")
parser.add_option("--test", dest="path_test_set", default="../../Data/090085/Road_Data/motor_trunk_pri_sec_tert_uncl_track/posneg_seg_coord_split_thr1_128_16_test")

parser.add_option("--norm", default="mean", dest="norm")
parser.add_option("--pos", type="int", default=0, dest="pos_num")
parser.add_option("--size", type="int", default=128, dest="size")
parser.add_option("-e", "--epoch", type="int", default=15, dest="epoch")
parser.add_option("--learning_rate", type="float", default=9e-6, dest="learning_rate")
parser.add_option("--batch", type="int", default=1, dest="batch_size")
parser.add_option("--rand", type="int", default=0, dest="rand_seed")

parser.add_option("--conv", dest="conv_struct")
parser.add_option("--not_weight", action="store_false", default=True, dest="use_weight")
parser.add_option("--no_biases", action="store_true", default=False, dest="no_biases")
parser.add_option("--use_batch_norm", action="store_true", default=False, dest="use_batch_norm")
parser.add_option("--scale_xen", action="store_true", default=False, dest="scale_xen")

parser.add_option("--gpu", default="", dest="gpu")
parser.add_option("--gpu_max_mem", type="float", default=0.9, dest="gpu_max_mem")

(options, args) = parser.parse_args()

path_train_set = options.path_train_set
path_cv_set = options.path_cv_set
path_test_set = options.path_test_set

save_path = options.save_path
model_name = options.model_name
record_summary = options.record_summary

pos_num = options.pos_num
norm = options.norm
size = options.size
epoch = options.epoch
batch_size = options.batch_size
learning_rate = options.learning_rate
rand_seed = options.rand_seed

conv_struct = options.conv_struct

use_weight = options.use_weight
use_batch_norm = options.use_batch_norm
scale_xen = options.scale_xen
no_biases = options.no_biases

gpu = options.gpu
gpu_max_mem = options.gpu_max_mem

# restrict to single gpu
os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
os.environ["CUDA_VISIBLE_DEVICES"] = gpu

if not save_path:
    print("no save path provided")
    sys.exit()

if norm.startswith('m'): norm = 'mean'
elif norm.startswith('G'): norm = 'Gaussian'
else: 
    print("norm = ", norm, " not in ('mean', 'Gaussian')")
    sys.exit()

if conv_struct == '0': assert not use_batch_norm

if not model_name:
    model_name = "Incep_"
    model_name += conv_struct + "_"
    model_name += norm[0] + "_"
    if use_weight: model_name += "weight_"
    if scale_xen: model_name += "scale_"
    if no_biases: model_name += "noB_"
    if use_batch_norm: model_name += "bn_"
    model_name += "p" + str(pos_num) + "_"
    model_name += "e" + str(epoch) + "_"
    model_name += "r" + str(rand_seed)
    
save_path = save_path.strip('/') + '/' + model_name + '/'

os.makedirs(os.path.dirname(save_path), exist_ok=True)
os.makedirs(os.path.dirname(save_path+'Analysis/'), exist_ok=True)

print("Train set:", path_train_set)
print("CV set:", path_cv_set)
print("will be saved as ", model_name)
print("will be saved into ", save_path)

# parse conv_struct: e.g. 3-16;5-8;1-32 | 3-8;1-16 | ...
# => concat[ 3x3 out_channel=16, 5x5 out_channel=8, 1x1 out_channel=32]
# => followed by inception concat [3x3 out_channel=8, 1x1 out_channel=16]
# => ...
# conv_struct = 0 => use only one 1x1 conv out_channel = classoutput

# note that at last layer, out_channel = 2 is requested
if not conv_struct:
    print("must provide structure for conv")
    sys.exit()
else:
    conv_struct = [[[int(x) for x in config.split('-')] for config in layer.split(';')] for layer in conv_struct.split('|')]
    print("conv_struct = ", conv_struct)

# import libraries
import numpy as np
import tensorflow as tf
import sklearn.metrics as skmt
import matplotlib
matplotlib.use('agg') # so that plt works in command line
import matplotlib.pyplot as plt
import scipy.io as sio
import skimage.io
import h5py
import os
import gc
import psutil

sys.path.append('../Metric/')
sys.path.append('../../Visualization/')
sys.path.append('../../Data_Preprocessing/')
from Metric import *
from Visualization import *
from Data_Extractor import *

# monitor mem usage
process = psutil.Process(os.getpid())
print('mem usage before data loaded:', process.memory_info().rss / 1024/1024, 'MB')
print()





''' Data preparation '''



# set random seed
np.random.seed(rand_seed)

# Load training set
train_set = h5py.File(path_train_set, 'r')
train_pos_topleft_coord = np.array(train_set['positive_example'])
train_neg_topleft_coord = np.array(train_set['negative_example'])
train_raw_image = np.array(train_set['raw_image'])
train_road_mask = np.array(train_set['road_mask'])
train_set.close()

# Load cross-validation set
CV_set = h5py.File(path_cv_set, 'r')
CV_pos_topleft_coord = np.array(CV_set['positive_example'])
CV_neg_topleft_coord = np.array(CV_set['negative_example'])
CV_raw_image = np.array(CV_set['raw_image'])
CV_road_mask = np.array(CV_set['road_mask'])
CV_set.close()

Train_Data = FCN_Data_Extractor (train_raw_image, train_road_mask, size,
                             pos_topleft_coord = train_pos_topleft_coord,
                             neg_topleft_coord = train_neg_topleft_coord,
                             normalization = norm)

CV_Data = FCN_Data_Extractor (CV_raw_image, CV_road_mask, size,
                          pos_topleft_coord = CV_pos_topleft_coord,
                          neg_topleft_coord = CV_neg_topleft_coord,
                          normalization = norm)
# run garbage collector
gc.collect()

print("train data:")
print(train_raw_image.shape, train_road_mask.shape)
print("pos = ", Train_Data.pos_size, "neg = ", Train_Data.neg_size)
print("cv data:")
print(CV_raw_image.shape, CV_road_mask.shape)
print("pos = ", CV_Data.pos_size, "neg = ", CV_Data.neg_size)

# monitor mem usage
process = psutil.Process(os.getpid())
print('mem usage after data loaded:', process.memory_info().rss / 1024/1024, 'MB')
print()



''' Create model '''



# general model parameter

band = 7

class_output = 2 # number of possible classifications for the problem
if use_weight:
    class_weight = [Train_Data.pos_size/Train_Data.size, Train_Data.neg_size/Train_Data.size]
    print(class_weight, '[neg, pos]')

iteration = int(Train_Data.size/batch_size) + 1

tf.reset_default_graph()
with tf.variable_scope('input'):
    x           = tf.placeholder(tf.float32, shape=[None, size, size, band], name='x')
    y           = tf.placeholder(tf.float32, shape=[None, size, size, class_output], name='y')
    weight      = tf.placeholder(tf.float32, shape=[None, size, size], name='weight')
    is_training = tf.placeholder(tf.bool, name='is_training') # batch norm

if use_batch_norm:
    normalizer_fn=tf.contrib.layers.batch_norm
    normalizer_params={'scale':True, 'is_training':is_training}
else:
    normalizer_fn=None
    normalizer_params=None

if no_biases: biases_initializer = None
else: biases_initializer = tf.zeros_initializer()

with tf.variable_scope('inception'):
    if conv_struct != [[[0]]]:
        net = tf.concat([tf.contrib.layers.conv2d(inputs=x, num_outputs=cfg[1], kernel_size=cfg[0], stride=1, padding='SAME',
                                                  normalizer_fn=normalizer_fn, normalizer_params=normalizer_params,biases_initializer=biases_initializer,
                                                  scope='0_'+str(cfg[0])+'-'+str(cfg[1])) 
                         for cfg in conv_struct[0]], axis=-1)

        if len(conv_struct) > 1:
            for layer_cnt in range(1,len(conv_struct)):
                layer_cfg = conv_struct[layer_cnt]
                net = tf.concat([tf.contrib.layers.conv2d(inputs=net, num_outputs=cfg[1], kernel_size=cfg[0], stride=1, padding='SAME',
                                                          normalizer_fn=normalizer_fn, normalizer_params=normalizer_params,biases_initializer=biases_initializer,
                                                          scope=str(layer_cnt)+'_'+str(cfg[0])+'-'+str(cfg[1])) 
                                 for cfg in layer_cfg], axis=-1)

    else:
        net = x

logits = tf.contrib.layers.conv2d(inputs=net, num_outputs=class_output, kernel_size=1, stride=1, padding='SAME', scope='logits')

with tf.variable_scope('prob_out'):
    prob_out = tf.nn.softmax(logits, name='prob_out')
    
with tf.variable_scope('cross_entropy'):
    flat_logits = tf.reshape(logits, (-1, class_output), name='flat_logits')    
    flat_labels = tf.to_float(tf.reshape(y, (-1, class_output)), name='flat_labels')
    flat_weight = tf.reshape(weight, [-1], name='flat_weight')

    cross_entropy = tf.losses.softmax_cross_entropy(flat_labels, flat_logits, weights=flat_weight)
    if scale_xen: cross_entropy = cross_entropy * size * size * band


# Ensures that we execute the update_ops before performing the train_step
update_ops = tf.get_collection(tf.GraphKeys.UPDATE_OPS)
with tf.control_dependencies(update_ops):
    train_step = tf.train.AdamOptimizer(learning_rate).minimize(cross_entropy)
    
if record_summary:            
    with tf.variable_scope('summary'):
        graph = tf.get_default_graph()

        # conv layers params
        conv_scopes = []
        if conv_struct != [[[0]]]:
            for layer_cnt in range(len(conv_struct)):
                layer_cfg = conv_struct[layer_cnt]

                for cfg in layer_cfg:
                    conv_scopes.append('inception/' + str(layer_cnt) +'_'+ str(cfg[0])+'-'+str(cfg[1]))
        for scope_name in conv_scopes:
            target_tensors = ['/weights:0']
            if use_batch_norm: target_tensors.extend(['/BatchNorm/gamma:0', '/BatchNorm/beta:0'])
            elif not no_biases: target_tensors.append('/biases:0')
            for tensor_name in target_tensors:
                tensor_name = scope_name + tensor_name
                cur_tensor = graph.get_tensor_by_name(tensor_name)
                tensor_name = tensor_name.split(':')[0]
                tf.summary.histogram(tensor_name, cur_tensor)
                tf.summary.histogram('grad_'+tensor_name, tf.gradients(cross_entropy, [cur_tensor])[0])

        # logits layer params
        scope_name = 'logits'
        target_tensors = ['/weights:0']
        if not no_biases: target_tensors.append('/biases:0')
        for tensor_name in target_tensors:
            tensor_name = scope_name + tensor_name
            cur_tensor = graph.get_tensor_by_name(tensor_name)
            tensor_name = tensor_name.split(':')[0]
            tf.summary.histogram(tensor_name, cur_tensor)
            tf.summary.histogram('grad_'+tensor_name, tf.gradients(cross_entropy, [cur_tensor])[0])

        # output layer
        tf.summary.image('input', tf.reverse(x[:,:,:,1:4], axis=[-1])) # axis must be of rank 1
        tf.summary.image('label', tf.expand_dims(y[:,:,:,1], axis=-1))
        tf.summary.image('prob_out_pos', tf.expand_dims(prob_out[:,:,:,1], axis=-1))
        tf.summary.image('prob_out_neg', tf.expand_dims(prob_out[:,:,:,0], axis=-1))
        tf.summary.image('logits_pos', tf.expand_dims(logits[:,:,:,1], axis=-1))
        tf.summary.image('logits_neg', tf.expand_dims(logits[:,:,:,0], axis=-1))
        tf.summary.scalar('cross_entropy', cross_entropy)
    merged_summary = tf.summary.merge_all()

# monitor mem usage
process = psutil.Process(os.getpid())
print('mem usage after model created:', process.memory_info().rss / 1024/1024, 'MB')
print()
sys.stdout.flush()



''' Train & monitor '''



saver = tf.train.Saver()

config = tf.ConfigProto()
config.gpu_options.per_process_gpu_memory_fraction = gpu_max_mem
sess = tf.InteractiveSession(config=config)
sess.run(tf.global_variables_initializer())

balanced_acc_curve = []
AUC_curve = []
avg_precision_curve = []
cross_entropy_curve = []
if record_summary: train_writer = tf.summary.FileWriter('./Summary/Inception/' + model_name, sess.graph)
for epoch_num in range(epoch):
    for iter_num in range(iteration):

        batch_x, batch_y, batch_w = Train_Data.get_patches(batch_size=batch_size, positive_num=pos_num, norm=True, weighted=use_weight)
        batch_x = batch_x.transpose((0, 2, 3, 1))

        train_step.run(feed_dict={x: batch_x, y: batch_y, weight: batch_w, is_training: True})

    if record_summary:
        # tensor board
        run_options = tf.RunOptions(trace_level=tf.RunOptions.FULL_TRACE)
        run_metadata = tf.RunMetadata()
        summary = sess.run(merged_summary, feed_dict={x: batch_x, y: batch_y, weight: batch_w, is_training: False}, options=run_options, run_metadata=run_metadata)

        train_writer.add_run_metadata(run_metadata, 'epoch_%03d' % (epoch_num+1))
        train_writer.add_summary(summary, epoch_num+1)
            
    # snap shot on CV set
    cv_metric = Metric_Record()
    cv_cross_entropy_list = []
    for batch_x, batch_y, batch_w in CV_Data.iterate_data(norm=True, weighted=use_weight):
        batch_x = batch_x.transpose((0, 2, 3, 1))

        [pred_prob, cross_entropy_cost] = sess.run([prob_out, cross_entropy], feed_dict={x: batch_x, y: batch_y, weight: batch_w, is_training: False})

        cv_metric.accumulate(Y         = np.array(batch_y.reshape(-1,class_output)[:,1]>0.5, dtype=int), 
                             pred      = np.array(pred_prob.reshape(-1,class_output)[:,1]>0.5, dtype=int), 
                             pred_prob = pred_prob.reshape(-1,class_output)[:,1])
        cv_cross_entropy_list.append(cross_entropy_cost)

    # calculate value
    balanced_acc = cv_metric.get_balanced_acc()
    AUC_score = skmt.roc_auc_score(np.array(cv_metric.y_true).flatten(), np.array(cv_metric.pred_prob).flatten())
    avg_precision_score = skmt.average_precision_score(np.array(cv_metric.y_true).flatten(), np.array(cv_metric.pred_prob).flatten())
    mean_cross_entropy = sum(cv_cross_entropy_list)/len(cv_cross_entropy_list)

    balanced_acc_curve.append(balanced_acc)
    AUC_curve.append(AUC_score)
    avg_precision_curve.append(avg_precision_score)
    cross_entropy_curve.append(mean_cross_entropy)

    print("mean_cross_entropy = ", mean_cross_entropy, "balanced_acc = ", balanced_acc, "AUC = ", AUC_score, "avg_precision = ", avg_precision_score)
    sys.stdout.flush()
print("finish")

# monitor mem usage
process = psutil.Process(os.getpid())
print('mem usage after model trained:', process.memory_info().rss / 1024/1024, 'MB')
print()

# plot training curve
plt.figsize=(9,5)
plt.plot(balanced_acc_curve, label='balanced_acc')
plt.plot(AUC_curve, label='AUC')
plt.plot(avg_precision_curve, label='avg_precision')
plt.legend()
plt.title('learning_curve_on_cross_validation')
plt.savefig(save_path+'Analysis/'+'cv_learning_curve.png', bbox_inches='tight')
plt.close()

plt.figsize=(9,5)
plt.plot(cross_entropy_curve)
plt.savefig(save_path+'Analysis/'+'cv_cross_entropy_curve.png', bbox_inches='tight')
plt.close()

# save model
saver.save(sess, save_path + model_name)

# run garbage collection
saved_sk_obj = 0
gc.collect()



''' Evaluate model '''



# train set eva
print("On training set:")
train_metric = Metric_Record()
train_cross_entropy_list = []
for batch_x, batch_y, batch_w in Train_Data.iterate_data(norm=True, weighted=use_weight):
    batch_x = batch_x.transpose((0, 2, 3, 1))

    [pred_prob, cross_entropy_cost] = sess.run([prob_out, cross_entropy], feed_dict={x: batch_x, y: batch_y, weight: batch_w, is_training: False})

    train_metric.accumulate(Y         = np.array(batch_y.reshape(-1,class_output)[:,1]>0.5, dtype=int),
                            pred      = np.array(pred_prob.reshape(-1,class_output)[:,1]>0.5, dtype=int), 
                            pred_prob = pred_prob.reshape(-1,class_output)[:,1])    
    train_cross_entropy_list.append(cross_entropy_cost)

train_metric.print_info()
AUC_score = skmt.roc_auc_score(np.array(train_metric.y_true).flatten(), np.array(train_metric.pred_prob).flatten())
avg_precision_score = skmt.average_precision_score(np.array(train_metric.y_true).flatten(), np.array(train_metric.pred_prob).flatten())
mean_cross_entropy = sum(train_cross_entropy_list)/len(train_cross_entropy_list)
print("mean_cross_entropy = ", mean_cross_entropy, "balanced_acc = ", balanced_acc, "AUC = ", AUC_score, "avg_precision = ", avg_precision_score)

# plot ROC curve
# fpr, tpr, thr = skmt.roc_curve(np.array(train_metric.y_true).flatten(), np.array(train_metric.pred_prob).flatten())
# plt.plot(fpr, tpr)
# plt.savefig(save_path+'Analysis/'+'train_ROC_curve.png', bbox_inches='tight')
# plt.close()

# cross validation eva
print("On CV set:")
cv_metric.print_info()

# plot ROC curve
# fpr, tpr, thr = skmt.roc_curve(np.array(cv_metric.y_true).flatten(), np.array(cv_metric.pred_prob).flatten())
# plt.plot(fpr, tpr)
# plt.savefig(save_path+'Analysis/'+'cv_ROC_curve.png', bbox_inches='tight')
# plt.close()
# sys.stdout.flush()

print("On test set:")
# Load training set
test_set = h5py.File(path_test_set, 'r')
test_pos_topleft_coord = np.array(test_set['positive_example'])
test_neg_topleft_coord = np.array(test_set['negative_example'])
test_raw_image = np.array(test_set['raw_image'])
test_road_mask = np.array(test_set['road_mask'])
test_set.close()

Test_Data = FCN_Data_Extractor (test_raw_image, test_road_mask, size,
                                pos_topleft_coord = test_pos_topleft_coord,
                                neg_topleft_coord = test_neg_topleft_coord,
                                normalization = norm)

test_metric = Metric_Record()
test_cross_entropy_list = []
for batch_x, batch_y, batch_w in Test_Data.iterate_data(norm=True, weighted=use_weight):
    batch_x = batch_x.transpose((0, 2, 3, 1))

    [pred_prob, cross_entropy_cost] = sess.run([prob_out, cross_entropy], feed_dict={x: batch_x, y: batch_y, weight: batch_w, is_training: False})

    test_metric.accumulate(Y         = np.array(batch_y.reshape(-1,class_output)[:,1]>0.5, dtype=int),
                            pred      = np.array(pred_prob.reshape(-1,class_output)[:,1]>0.5, dtype=int), 
                            pred_prob = pred_prob.reshape(-1,class_output)[:,1])    
    test_cross_entropy_list.append(cross_entropy_cost)

test_metric.print_info()
AUC_score = skmt.roc_auc_score(np.array(test_metric.y_true).flatten(), np.array(test_metric.pred_prob).flatten())
avg_precision_score = skmt.average_precision_score(np.array(test_metric.y_true).flatten(), np.array(test_metric.pred_prob).flatten())
mean_cross_entropy = sum(test_cross_entropy_list)/len(test_cross_entropy_list)
print("mean_cross_entropy = ", mean_cross_entropy, "balanced_acc = ", balanced_acc, "AUC = ", AUC_score, "avg_precision = ", avg_precision_score)

print("end of scripts")
# # run garbage collection
# train_metric = 0
# cv_metric = 0
# test_metric = 0
# gc.collect()


# # Predict road mask
# # Predict road prob masks on train
# train_pred_road = np.zeros([x for x in train_road_mask.shape] + [2])
# for coord, patch in Train_Data.iterate_raw_image_patches_with_coord(norm=True):
#     patch = patch.transpose((0, 2, 3, 1))
#     train_pred_road[coord[0]:coord[0]+size, coord[1]:coord[1]+size, :] += logits.eval(feed_dict={x: patch, is_training: False})[0]

# # Predict road prob on CV
# CV_pred_road = np.zeros([x for x in CV_road_mask.shape] + [2])
# for coord, patch in CV_Data.iterate_raw_image_patches_with_coord(norm=True):
#     patch = patch.transpose((0, 2, 3, 1))
#     CV_pred_road[coord[0]:coord[0]+size, coord[1]:coord[1]+size, :] += logits.eval(feed_dict={x: patch, is_training: False})[0]

# # save prediction
# prediction_name = model_name + '_pred.h5'
# h5f_file = h5py.File(save_path + prediction_name, 'w')
# h5f_file.create_dataset (name='train_pred', data=train_pred_road)
# h5f_file.create_dataset (name='CV_pred', data=CV_pred_road)
# h5f_file.close()

# # monitor mem usage
# process = psutil.Process(os.getpid())
# print('mem usage after prediction maps calculated:', process.memory_info().rss / 1024/1024, 'MB')
# print()