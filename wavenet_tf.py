import tensorflow as tf


import matplotlib.pyplot as plt

import os
import sys
import time
import numpy as np
from six.moves import xrange  # pylint: disable=redefined-builtin
import h5py

import config
from data_pipeline_wavenet import data_gen
import modules_tf as modules
import utils
from reduce import mgc_to_mfsc


def binary_cross(p,q):
    return -(p * tf.log(q + 1e-12) + (1 - p) * tf.log( 1 - q + 1e-12))

def train(_):
    with tf.Graph().as_default():
        
        input_placeholder = tf.placeholder(tf.float32, shape=(config.batch_size,config.max_phr_len,config.input_features),name='input_placeholder')
        tf.summary.histogram('conditioning', input_placeholder)
        input_placeholder_2 = tf.placeholder(tf.float32, shape=(config.batch_size,config.max_phr_len,config.output_features),name='input_placeholder')
        tf.summary.histogram('inputs', input_placeholder)
        target_placeholder = tf.placeholder(tf.float32, shape=(config.batch_size,config.max_phr_len,config.output_features),name='target_placeholder')
        tf.summary.histogram('targets', target_placeholder)


        output,vuv = modules.wavenet(input_placeholder_2,input_placeholder)

        harm = output[:,:,:60]
        ap = output[:,:,60:64]
        f0 = output[:,:,-1:]


        tf.summary.histogram('harm', harm)

        tf.summary.histogram('ap', ap)

        tf.summary.histogram('f0', f0)

        tf.summary.histogram('vuv', vuv)

        harm_loss = tf.reduce_sum(tf.abs(harm - target_placeholder[:,:,:60])*np.linspace(1.0,0.7,60)*(1-target_placeholder[:,:,-1:]))

        ap_loss = tf.reduce_sum(tf.abs(ap - target_placeholder[:,:,60:-2])*(1-target_placeholder[:,:,-1:]))

        f0_loss = tf.reduce_sum(tf.abs(f0 - target_placeholder[:,:,-2:-1])*20.0*(1-target_placeholder[:,:,-1:])) 

        # vuv_loss = tf.reduce_sum(tf.nn.sigmoid_cross_entropy_with_logits(labels=, logits=vuv))

        vuv_loss = tf.reduce_mean(tf.reduce_sum(binary_cross(target_placeholder[:,:,-1:],vuv)))

        loss = harm_loss + ap_loss + f0_loss + vuv_loss

        harm_summary = tf.summary.scalar('harm_loss', harm_loss)

        ap_summary = tf.summary.scalar('ap_loss', ap_loss)

        f0_summary = tf.summary.scalar('f0_loss', f0_loss)

        vuv_summary = tf.summary.scalar('vuv_loss', vuv_loss)

        loss_summary = tf.summary.scalar('total_loss', loss)

        global_step = tf.Variable(0, name='global_step', trainable=False)

        optimizer = tf.train.AdamOptimizer(learning_rate = config.init_lr)

        train_function = optimizer.minimize(loss, global_step= global_step)

        # train_harm = optimizer.minimize(harm_loss, global_step= global_step)

        # train_ap = optimizer.minimize(ap_loss, global_step= global_step)

        # train_f0 = optimizer.minimize(f0_loss, global_step= global_step)

        # train_vuv = optimizer.minimize(vuv_loss, global_step= global_step)

        summary = tf.summary.merge_all()

        init_op = tf.group(tf.global_variables_initializer(), tf.local_variables_initializer())
        saver = tf.train.Saver()
        sess = tf.Session()

        sess.run(init_op)

        ckpt = tf.train.get_checkpoint_state(config.log_dir)

        if ckpt and ckpt.model_checkpoint_path:
            print("Using the model in %s"%ckpt.model_checkpoint_path)
            saver.restore(sess, ckpt.model_checkpoint_path)


        train_summary_writer = tf.summary.FileWriter(config.log_dir+'train/', sess.graph)
        val_summary_writer = tf.summary.FileWriter(config.log_dir+'val/', sess.graph)

        
        start_epoch = int(sess.run(tf.train.get_global_step())/(config.batches_per_epoch_train))

        print("Start from: %d" % start_epoch)
        for epoch in xrange(start_epoch, config.num_epochs):
            teacher_prob = config.get_teacher_prob(epoch)
            data_generator = data_gen()
            start_time = time.time()

            epoch_loss_harm = 0
            epoch_loss_ap = 0
            epoch_loss_f0 = 0
            epoch_loss_vuv = 0
            epoch_total_loss = 0

            epoch_loss_harm_val = 0
            epoch_loss_ap_val = 0
            epoch_loss_f0_val = 0
            epoch_loss_vuv_val = 0
            epoch_total_loss_val = 0

            batch_num = 0
            batch_num_val = 0
            val_generator = data_gen(mode='val')

            # val_generator = get_batches(train_filename=config.h5py_file_val, batches_per_epoch=config.batches_per_epoch_val)

            with tf.variable_scope('Training'):

                for voc, feat in data_generator:

                    teacher_learn = np.random.rand(1)<teacher_prob

                    if teacher_learn:

                        past = feat[:,:-1,:]+(np.random.rand(config.batch_size,config.max_phr_len,config.output_features)*config.noise)

                        _, step_loss_harm, step_loss_ap, step_loss_f0, step_loss_vuv, step_total_loss = sess.run([train_function, harm_loss, ap_loss, f0_loss, vuv_loss, loss], 
                            feed_dict={input_placeholder_2: past,input_placeholder: voc[:,1:,:],target_placeholder: feat[:,1:,:]})
                    else : 
                        outputs = np.zeros((config.batch_size,config.max_phr_len,config.output_features))
                        step_loss_harm = 0
                        step_loss_ap = 0
                        step_loss_f0 = 0 
                        step_loss_vuv = 0
                        step_total_loss = 0
                        for index in range(config.max_phr_len):
                            # import pdb;pdb.set_trace()
                            feed_dict={input_placeholder: voc[:,1:,:], input_placeholder_2: outputs, target_placeholder: feat[:,1:,:]}
                            _,ab ,bc ,cd ,de ,ef, op,vu  = sess.run([train_function, harm_loss, ap_loss, f0_loss, vuv_loss, loss, output,vuv],feed_dict=feed_dict)
                            step_loss_harm+=ab
                            step_loss_ap+=bc
                            step_loss_f0+=cd
                            step_loss_vuv+=de
                            step_total_loss+=ef
                            op = np.concatenate((op,vu),axis=-1)
                            outputs [:,:index,:] = op[:,:index,:]


                    # _, step_loss_harm = sess.run([train_harm, harm_loss], feed_dict={input_placeholder: voc,target_placeholder: feat})
                    # _, step_loss_ap = sess.run([train_ap, ap_loss], feed_dict={input_placeholder: voc,target_placeholder: feat})
                    # _, step_loss_f0 = sess.run([train_f0, f0_loss], feed_dict={input_placeholder: voc,target_placeholder: feat})
                    # _, step_loss_vuv = sess.run([train_vuv, vuv_loss], feed_dict={input_placeholder: voc,target_placeholder: feat})

                    epoch_loss_harm+=step_loss_harm
                    epoch_loss_ap+=step_loss_ap
                    epoch_loss_f0+=step_loss_f0
                    epoch_loss_vuv+=step_loss_vuv
                    epoch_total_loss+=step_total_loss
                    utils.progress(batch_num,config.batches_per_epoch_train, suffix = 'training done')
                    batch_num+=1


                
                epoch_loss_harm = epoch_loss_harm/(config.batches_per_epoch_train *config.batch_size*config.max_phr_len*60)
                epoch_loss_ap = epoch_loss_ap/(config.batches_per_epoch_train *config.batch_size*config.max_phr_len*4)
                epoch_loss_f0 = epoch_loss_f0/(config.batches_per_epoch_train *config.batch_size*config.max_phr_len)
                epoch_loss_vuv = epoch_loss_vuv/(config.batches_per_epoch_train *config.batch_size*config.max_phr_len)
                epoch_total_loss = epoch_total_loss/(config.batches_per_epoch_train *config.batch_size*config.max_phr_len*66)

                summary_str = sess.run(summary, feed_dict={input_placeholder_2: feat[:,:-1,:],input_placeholder: voc[:,:-1,:],target_placeholder: feat[:,1:,:]})
                train_summary_writer.add_summary(summary_str, epoch)
                # summary_writer.add_summary(summary_str_val, epoch)
                train_summary_writer.flush()

            with tf.variable_scope('Validation'):

                for voc, feat in val_generator:
                    step_loss_harm_val = sess.run(harm_loss, feed_dict={input_placeholder_2: feat[:,:-1,:],input_placeholder: voc[:,:-1,:],target_placeholder: feat[:,1:,:]})
                    step_loss_ap_val = sess.run(ap_loss, feed_dict={input_placeholder_2: feat[:,:-1,:],input_placeholder: voc[:,:-1,:],target_placeholder: feat[:,1:,:]})
                    step_loss_f0_val = sess.run(f0_loss, feed_dict={input_placeholder_2: feat[:,:-1,:],input_placeholder: voc[:,:-1,:],target_placeholder: feat[:,1:,:]})
                    step_loss_vuv_val = sess.run(vuv_loss, feed_dict={input_placeholder_2: feat[:,:-1,:],input_placeholder: voc[:,:-1,:],target_placeholder: feat[:,1:,:]})
                    step_total_loss_val = sess.run(loss, feed_dict={input_placeholder_2: feat[:,:-1,:],input_placeholder: voc[:,:-1,:],target_placeholder: feat[:,1:,:]})

                    epoch_loss_harm_val+=step_loss_harm_val
                    epoch_loss_ap_val+=step_loss_ap_val
                    epoch_loss_f0_val+=step_loss_f0_val
                    epoch_loss_vuv_val+=step_loss_vuv_val
                    epoch_total_loss_val+=step_total_loss_val

                    utils.progress(batch_num_val,config.batches_per_epoch_val, suffix = 'validiation done')
                    batch_num_val+=1

                epoch_loss_harm_val = epoch_loss_harm_val/(config.batches_per_epoch_val *config.batch_size*config.max_phr_len*60)
                epoch_loss_ap_val = epoch_loss_ap_val/(config.batches_per_epoch_val *config.batch_size*config.max_phr_len*4)
                epoch_loss_f0_val = epoch_loss_f0_val/(config.batches_per_epoch_val *config.batch_size*config.max_phr_len)
                epoch_loss_vuv_val = epoch_loss_vuv_val/(config.batches_per_epoch_val *config.batch_size*config.max_phr_len)
                epoch_total_loss_val = epoch_total_loss_val/(config.batches_per_epoch_val *config.batch_size*config.max_phr_len*66)

                summary_str = sess.run(summary, feed_dict={input_placeholder_2: feat[:,:-1,:],input_placeholder: voc[:,1:,:],target_placeholder: feat[:,1:,:]})
                val_summary_writer.add_summary(summary_str, epoch)
                # summary_writer.add_summary(summary_str_val, epoch)
                val_summary_writer.flush()

            duration = time.time() - start_time

            if (epoch+1) % config.print_every == 0:
                # Print status to stdout.
                print('epoch %d: Harm Training Loss = %.10f (%.3f sec)' % (epoch+1, epoch_loss_harm, duration))
                print('        : Ap Training Loss = %.10f ' % (epoch_loss_ap))
                print('        : F0 Training Loss = %.10f ' % (epoch_loss_f0))
                print('        : VUV Training Loss = %.10f ' % (epoch_loss_vuv))

                print('        : Harm Validation Loss = %.10f ' % (epoch_loss_harm_val))
                print('        : Ap Validation Loss = %.10f ' % (epoch_loss_ap_val))
                print('        : F0 Validation Loss = %.10f ' % (epoch_loss_f0_val))
                print('        : VUV Validation Loss = %.10f ' % (epoch_loss_vuv_val))

                # Update the events file.



            if (epoch + 1) % config.save_every == 0 or (epoch + 1) == config.num_epochs:
                checkpoint_file = os.path.join(config.log_dir, 'model.ckpt')
                saver.save(sess, checkpoint_file, global_step=epoch)


def synth_file(file_name, file_path=config.wav_dir, show_plots=True, save_file=True):
    debug = False
    if file_name.startswith('ikala'):
        file_name = file_name[6:]
        file_path = config.wav_dir
        utils.write_ori_ikala(os.path.join(file_path,file_name),file_name)
    elif file_name.startswith('mir'):
        file_name = file_name[4:]
        file_path = config.wav_dir_mir
        utils.write_ori_ikala(os.path.join(file_path,file_name),file_name)
    stat_file = h5py.File(config.stat_dir+'stats.hdf5', mode='r')

    max_feat = np.array(stat_file["feats_maximus"])
    min_feat = np.array(stat_file["feats_minimus"])
    max_voc = np.array(stat_file["voc_stft_maximus"])
    min_voc = np.array(stat_file["voc_stft_minimus"])
    max_back = np.array(stat_file["back_stft_maximus"])
    min_back = np.array(stat_file["back_stft_minimus"])
    max_mix = np.array(max_voc)+np.array(max_back)

    with tf.Graph().as_default():
        
        input_placeholder = tf.placeholder(tf.float32, shape=(1,config.max_phr_len,config.input_features),name='input_placeholder')
        tf.summary.histogram('conditioning', input_placeholder)
        input_placeholder_2 = tf.placeholder(tf.float32, shape=(1,config.max_phr_len,config.output_features),name='input_placeholder')
        tf.summary.histogram('inputs', input_placeholder)


        output,vuv = modules.wavenet(input_placeholder_2,input_placeholder)


        saver = tf.train.Saver()


        init_op = tf.group(tf.global_variables_initializer(), tf.local_variables_initializer())
        sess = tf.Session()

        sess.run(init_op)

        ckpt = tf.train.get_checkpoint_state(config.log_dir)

        if ckpt and ckpt.model_checkpoint_path:
            print("Using the model in %s"%ckpt.model_checkpoint_path)
            saver.restore(sess, ckpt.model_checkpoint_path)

        mix_stft = utils.file_to_stft(os.path.join(file_path,file_name))

        mix_stft = mix_stft/max_mix

        lent = len(mix_stft)

        mix_stft_in = np.pad(mix_stft,[(0,config.max_phr_len),(0,0)],'constant')

        # import pdb;pdb.set_trace()

        targs = utils.input_to_feats(os.path.join(file_path,file_name))

        outputs = np.zeros((1,config.max_phr_len,config.output_features))

        opus = []

        i = 0


        for index in range(lent):
            inputs = mix_stft_in[index:index+config.max_phr_len,:]

            if outputs.shape[1]>config.max_phr_len:
                inpy = inputs.reshape(1,config.max_phr_len,-1)
                outpy = outputs[:,-config.max_phr_len:,:]
            else:
                inpy = inputs.reshape(1,config.max_phr_len,-1)
                outpy = outputs
                
            # import pdb;pdb.set_trace()
            op,vu = sess.run([output,vuv], feed_dict={input_placeholder: inpy, input_placeholder_2: outpy})
            op = np.concatenate((op,vu),axis=-1)
            if debug:
                plt.figure(1)
                plt.subplot(311)
                plt.imshow(np.log(inputs.T),aspect='auto',origin='lower')
                plt.subplot(312)
                plt.imshow(targs[index:index+config.max_phr_len,:].T,aspect='auto',origin='lower')
                plt.subplot(313)
                plt.imshow(outpy.reshape(config.max_phr_len,-1).T,aspect='auto',origin='lower')
                plt.show()
                import pdb;pdb.set_trace()

            if index>config.max_phr_len:
                outputs = np.append(outputs,op[:,-1:,:],axis =1)
            else:
                outputs[:,:index,:] = op[:,:index,:]

        val_outer = outputs[0]  
        val_outer[:,-1] = np.round(val_outer[:,-1])
        val_outer = val_outer[:targs.shape[0],:]
        val_outer = np.clip(val_outer,0.0,1.0)

        #Test purposes only
        

        # targs = utils.normalize(targs, 'feats', mode=config.norm_mode_out)
        targs = (targs-min_feat)/(max_feat-min_feat)


        

        if show_plots:

            # import pdb;pdb.set_trace()
        
            ins = val_outer[:,:60]
            outs = targs[:,:60]
            plt.figure(1)
            ax1 = plt.subplot(211)
            plt.imshow(ins.T, origin='lower', aspect='auto')
            ax1.set_title("Predicted Harm ", fontsize = 10)
            ax2 = plt.subplot(212)
            plt.imshow(outs.T, origin='lower', aspect='auto')
            ax2.set_title("Ground Truth Harm ", fontsize = 10)
            plt.figure(2)
            ax1 = plt.subplot(211)
            plt.imshow(val_outer[:,60:-2].T, origin='lower', aspect='auto')
            ax1.set_title("Predicted Aperiodic Part", fontsize = 10)
            ax2 = plt.subplot(212)
            plt.imshow(targs[:,60:-2].T, origin='lower', aspect='auto')
            ax2.set_title("Ground Truth Aperiodic Part", fontsize = 10)
            plt.figure(3)
            uu = val_outer[:,-2]*(1-targs[:,-1])
            uu[uu == 0] = np.nan
            plt.plot(uu, label = "Predicted Value")
            uu = targs[:,-2]*(1-targs[:,-1])
            uu[uu == 0] = np.nan
            plt.plot(uu, label="Ground Truth")
            # uu = f0_sac[:,0]*(1-f0_sac[:,1])
            # uu[uu == 0] = np.nan
            # plt.plot(uu, label="Sac f0")
            plt.legend()
            plt.figure(4)
            ax1 = plt.subplot(211)
            plt.plot(val_outer[:,-1])
            ax1.set_title("Predicted Voiced/Unvoiced", fontsize = 10)
            ax2 = plt.subplot(212)
            plt.plot(targs[:,-1])
            ax2.set_title("Ground Truth Voiced/Unvoiced", fontsize = 10)
            plt.show()
        if save_file:
            
            val_outer = np.ascontiguousarray(val_outer*(max_feat-min_feat)+min_feat)
            targs = np.ascontiguousarray(targs*(max_feat-min_feat)+min_feat)

            # val_outer = np.ascontiguousarray(utils.denormalize(val_outer,'feats', mode=config.norm_mode_out))
            try:
                utils.feats_to_audio(val_outer,file_name[:-4]+'_synth_pred_f0')
                print("File saved to %s" % config.val_dir+file_name[:-4]+'_synth_pred_f0.wav')
            except:
                print("Couldn't synthesize with predicted f0")
            try:
                val_outer[:,-2:] = targs[:,-2:]
                utils.feats_to_audio(val_outer,file_name[:-4]+'_synth_ori_f0')
                print("File saved to %s" % config.val_dir+file_name[:-4]+'_synth_ori_f0.wav')
            except:
                print("Couldn't synthesize with original f0")
                




if __name__ == '__main__':
    if sys.argv[1] == '-train' or sys.argv[1] == '--train' or sys.argv[1] == '--t' or sys.argv[1] == '-t':
        print("Training")
        tf.app.run(main=train)
    elif sys.argv[1] == '-synth' or sys.argv[1] == '--synth' or sys.argv[1] == '--s' or sys.argv[1] == '-s':
        if len(sys.argv)<3:
            print("Please give a file to synthesize")
        else:
            file_name = sys.argv[2]
            if not file_name.endswith('.wav'):
                file_name = file_name+'.wav'
            print("Synthesizing File %s"% file_name)
            if '-p' in sys.argv or '--p' in sys.argv or '-plot' in sys.argv or '--plot' in sys.argv:
                
                if '-ns' in sys.argv or '--ns' in sys.argv or '-nosave' in sys.argv or '--nosave' in sys.argv:
                    print("Just showing plots for File %s"% sys.argv[2])
                    synth_file(file_name,show_plots=True, save_file=False)
                else:
                    print("Synthesizing File %s And Showing Plots"% sys.argv[2])
                    synth_file(file_name,show_plots=True, save_file=True)
            else:
                print("Synthesizing File %s, Not Showing Plots"% sys.argv[2])
                synth_file(file_name,show_plots=False, save_file=True)

    elif sys.argv[1] == '-help' or sys.argv[1] == '--help' or sys.argv[1] == '--h' or sys.argv[1] == '-h':
        print("%s --train to train the model"%sys.argv[0])
        print("%s --synth <filename> to synthesize file"%sys.argv[0])
        print("%s --synth <filename> -- plot to synthesize file and show plots"%sys.argv[0])
        print("%s --synth <filename> -- plot --ns to just show plots"%sys.argv[0])
    else:
        print("Unable to decipher inputs please use %s --help for help on how to use this function"%sys.argv[0])
  


