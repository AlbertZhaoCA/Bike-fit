from flask import Flask, request, jsonify
import os
import tempfile
import tensorflow as tf
import tensorflow_hub as hub
import numpy as np
import cv2
import kagglehub

# from preprocessing import reduce_video_quality,load_tensors_from_clip
from model import load_model_from_tfhub, get_keypoints_from_video
from postprocessing import (find_camera_facing_side,
                            get_front_keypoint_indices,
                            get_lowest_pedal_frames,
                            filter_bad_knee_angles,
                            get_hip_knee_ankle_angle,
                            get_highest_pedal_frames,
                            calculate_angle)

"""
    初始化函数，用于加载MoveNet Thunder模型。

    该函数通过调用load_model_from_tfhub函数来加载模型。
    并且初始化两个全局变量：model和input_size，分别用于存储加载的模型和模型输入的大小。
    """
def init():

    global model, input_size
    model, input_size = load_model_from_tfhub()

def upload_video(path):
    init()

    clip, tensors = pre_process_video(path)

    all_keypoints = get_keypoints_from_video(tensors, model, input_size)

    result = get_pose(all_keypoints)

    return result

#视频前处理
def pre_process_video(file_path):
    """
    使用OpenCV预处理视频文件。
    
    参数:
    file_path (str): 视频文件的路径
    
    返回:
    tuple: 包含处理后的视频帧和张量数据
    """
    # 打开视频文件
    cap = cv2.VideoCapture(file_path)
    if not cap.isOpened():
        raise ValueError("无法打开视频文件")
    
    # 获取视频属性
    fps = int(cap.get(cv2.CAP_PROP_FPS))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    # 限制处理帧数
    max_frames = min(total_frames, fps * 10)  # 最多处理10秒的视频
    target_size = (256, 256)  # 目标尺寸
    
    frames = []
    tensors = []
    
    for _ in range(max_frames):
        ret, frame = cap.read()
        if not ret:
            break
            
        # 调整帧大小
        frame = cv2.resize(frame, target_size)
        # 转换颜色空间从BGR到RGB
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        frames.append(frame)
        # 转换为张量
        tensor = tf.convert_to_tensor(frame)
        tensor = tf.expand_dims(tensor, axis=0)
        tensor = tf.cast(tensor, dtype=tf.int32)
        tensors.append(tensor)
    
    cap.release()
    
    return frames, tf.concat(tensors, axis=0)

#找到膝盖角度的最小值和对应的帧率，并返回平均值和方差
def knee_pose_process_video(all_keypoints):
    facing_direction = find_camera_facing_side(all_keypoints[0])

    hip_knee_ankle_indices = get_front_keypoint_indices(facing_direction)[:4]  # 存储拍摄视角侧的髋部，膝盖和脚踝的位置索引

    # 获取所有帧的膝盖角度
    knee_angles = [
        get_hip_knee_ankle_angle(kp, hip_knee_ankle_indices)
        for kp in all_keypoints
    ]

    # 找到踏板角度最低的帧
    lowest_pedal_point_indices = get_lowest_pedal_frames(
        all_keypoints, hip_knee_ankle_indices
    )

    # 从所有踏板角度中找到最位置最低的帧的膝盖角度
    angles_at_lowest_pedal_points = [
        knee_angles[i] for i in lowest_pedal_point_indices
    ]

    # 排除不正常的角度和帧，进一步增加稳定性
    filtered_angles, filtered_indices = filter_bad_knee_angles(
        angles_at_lowest_pedal_points, lowest_pedal_point_indices
    )

    # 取最小膝盖角度的平均数和方差
    if len(filtered_angles) > 0:
        angle_avg = np.mean(filtered_angles)
        angle_std = np.std(filtered_angles)
    else:
        angle_avg = 0
        angle_std = 0

    return (
        angle_avg,
        angle_std,
        filtered_indices,
        knee_angles,
    )

#获取髋，膝盖，肩膀，手肘的角度
def get_pose(all_keypoints):
    facing_direction = find_camera_facing_side(all_keypoints[0])
    front_indices = get_front_keypoint_indices(facing_direction)

    # 获取膝盖最低点角度的平均数
    knee_angle_lowest = get_knee_angle_at_lowest_pedal_points_avg(all_keypoints)
    
    # 获取膝盖最高点角度的平均数
    knee_angle_highest = get_knee_angle_at_highest_pedal_points_avg(all_keypoints)
    
    # 获取肩膀角度的平均数
    shoulder_angle = get_shoulder_angle_avg(all_keypoints, front_indices)
    
    # 获取手肘角度的平均数
    elbow_angle = get_elbow_angle_avg(all_keypoints, front_indices)

    # 获取髋关节角度的平均数
    hip_angle = get_hip_angle_avg(all_keypoints, front_indices)

    # 获取所有帧的膝盖角度（用于绘图）
    hip_knee_ankle_indices = front_indices[:4]
    knee_angles = [
        get_hip_knee_ankle_angle(kp, hip_knee_ankle_indices)
        for kp in all_keypoints
    ]

    # 创建测量结果字典
    measurements = {
        'knee_angle_lowest': knee_angle_lowest,
        'knee_angle_highest': knee_angle_highest,
        'shoulder_angle': shoulder_angle,
        'elbow_angle': elbow_angle,
        'hip_angle': hip_angle,
        'knee_angles': knee_angles,
    }

    return measurements

#获取膝盖最大角度的平均数
def get_knee_angle_at_lowest_pedal_points_avg(all_keypoints):
    facing_direction = find_camera_facing_side(all_keypoints[0])

    hip_knee_ankle_indices = get_front_keypoint_indices(facing_direction)[:4]  # 存储拍摄视角侧的髋部，膝盖和脚踝的位置索引

    # 获取所有帧的膝盖角度
    knee_angles = [
        get_hip_knee_ankle_angle(kp, hip_knee_ankle_indices)
        for kp in all_keypoints
    ]

    # 找到踏板角度最低的帧
    lowest_pedal_point_indices = get_lowest_pedal_frames(
        all_keypoints, hip_knee_ankle_indices
    )

    # 从所有踏板角度中找到最位置最低的帧的膝盖角度
    angles_at_lowest_pedal_points = [
        knee_angles[i] for i in lowest_pedal_point_indices
    ]

    # 排除不正常的角度和帧，进一步增加稳定性
    filtered_angles, filtered_indices = filter_bad_knee_angles(
        angles_at_lowest_pedal_points, lowest_pedal_point_indices
    )

    # 取最小膝盖角度的平均数和方差
    if len(filtered_angles) > 0:
        angle_avg = np.mean(filtered_angles)
        angle_std = np.std(filtered_angles)
    else:
        angle_avg = 0
        angle_std = 0

    return angle_avg

#获取膝盖最小角度的平均数

def get_knee_angle_at_highest_pedal_points_avg(all_keypoints):
    facing_direction = find_camera_facing_side(all_keypoints[0])

    hip_knee_ankle_indices = get_front_keypoint_indices(facing_direction)[:4]  # 存储拍摄视角侧的髋部，膝盖和脚踝的位置索引

    # 获取所有帧的膝盖角度
    knee_angles = [
        get_hip_knee_ankle_angle(kp, hip_knee_ankle_indices)
        for kp in all_keypoints
    ]

    # 找到踏板角度最高的帧
    highest_pedal_point_indices = get_highest_pedal_frames(
        all_keypoints, hip_knee_ankle_indices
    )

    # 从所有踏板角度中找到最位置最高的帧的膝盖角度
    angles_at_highest_pedal_points = [
        knee_angles[i] for i in highest_pedal_point_indices
    ]

    # 取最小膝盖角度的平均数和方差
    if len(angles_at_highest_pedal_points) > 0:
        angle_avg = np.mean(angles_at_highest_pedal_points)
    else:
        angle_avg = 0

    return angle_avg

#获取肩膀角度的平均数
def get_shoulder_angle_avg(all_keypoints, front_indices):
    shoulder_index = front_indices[3]  # 肩膀索引
    wrist_index = front_indices[5]  # 手腕索引
    elbow_index = front_indices[4]  # 手肘索引

    # 计算所有帧的肩膀角度
    shoulder_angles = []
    for kp in all_keypoints:
        # 获取三个点的坐标
        [shoulder_y, shoulder_x] = kp[shoulder_index][0:-1]
        [elbow_y, elbow_x] = kp[elbow_index][0:-1]
        [wrist_y, wrist_x] = kp[wrist_index][0:-1]
        
        # 计算角度
        angle = calculate_angle((wrist_y, wrist_x), (elbow_y, elbow_x), (shoulder_y, shoulder_x))
        shoulder_angles.append(angle)

    # 取所有肩膀角度的平均值
    if len(shoulder_angles) > 0:
        shoulder_angle_avg = np.mean(shoulder_angles)
    else:
        shoulder_angle_avg = 0

    return shoulder_angle_avg

#获取手肘角度的平均数
def get_elbow_angle_avg(all_keypoints, front_indices):
    shoulder_index = front_indices[3]  # 肩膀索引
    elbow_index = front_indices[4]  # 手肘索引
    wrist_index = front_indices[5]  # 手腕索引

    # 计算所有帧的手肘角度
    elbow_angles = []
    for kp in all_keypoints:
        # 获取三个点的坐标
        [shoulder_y, shoulder_x] = kp[shoulder_index][0:-1]
        [elbow_y, elbow_x] = kp[elbow_index][0:-1]
        [wrist_y, wrist_x] = kp[wrist_index][0:-1]
        
        # 计算角度
        angle = calculate_angle((shoulder_y, shoulder_x), (elbow_y, elbow_x), (wrist_y, wrist_x))
        elbow_angles.append(angle)

    # 取所有手肘角度的平均值
    if len(elbow_angles) > 0:
        elbow_angle_avg = np.mean(elbow_angles)
    else:
        elbow_angle_avg = 0

    return elbow_angle_avg

#获取髋关节角度的平均数
def get_hip_angle_avg(all_keypoints, front_indices):
    shoulder_index = front_indices[3]  # 肩膀索引
    hip_index = front_indices[0]  # 髋关节索引
    knee_index = front_indices[1]  # 膝盖索引

    # 计算所有帧的髋关节角度
    hip_angles = []
    for kp in all_keypoints:
        # 获取三个点的坐标
        [shoulder_y, shoulder_x] = kp[shoulder_index][0:-1]
        [hip_y, hip_x] = kp[hip_index][0:-1]
        [knee_y, knee_x] = kp[knee_index][0:-1]
        
        # 计算角度
        angle = calculate_angle((shoulder_y, shoulder_x), (hip_y, hip_x), (knee_y, knee_x))
        hip_angles.append(angle)

    # 取所有髋关节角度的平均值
    if len(hip_angles) > 0:
        hip_angle_avg = np.mean(hip_angles)
    else:
        hip_angle_avg = 0

    return hip_angle_avg

def test_pose_analyzer():
    """
    测试函数，用于验证姿态分析器的各项功能
    """
    # 测试初始化
    print("1. 测试模型初始化...")
    try:
        init()
        print("✓ 模型初始化成功")
    except Exception as e:
        print(f"✗ 模型初始化失败: {str(e)}")

    # 测试视频预处理
    print("\n2. 测试视频预处理...")
    try:
        # 使用当前目录下的测试视频
        current_dir = os.path.dirname(os.path.abspath(__file__))
        test_video_path = os.path.join(current_dir, "uploads", "raw.mp4")
        
        if not os.path.exists(test_video_path):
            print(f"✗ 测试视频不存在: {test_video_path}")
            return
            
        frames, tensors = pre_process_video(test_video_path)
        
        # 验证预处理结果
        print(f"  - 处理的视频帧数: {len(frames)}")
        print(f"  - 张量形状: {tensors.shape}")
        print(f"  - 张量数据类型: {tensors.dtype}")
        print(f"  - 张量值范围: [{tf.reduce_min(tensors):.2f}, {tf.reduce_max(tensors):.2f}]")
        print("✓ 视频预处理成功")
    except Exception as e:
        print(f"✗ 视频预处理失败: {str(e)}")

    # 测试姿态检测
    print("\n3. 测试姿态检测...")
    try:
        all_keypoints = get_keypoints_from_video(tensors, model, input_size)
        print(f"  - 关键点数量: {len(all_keypoints)}")
        print(f"  - 单帧关键点形状: {all_keypoints[0].shape}")
        print("✓ 姿态检测成功")
    except Exception as e:
        print(f"✗ 姿态检测失败: {str(e)}")

    # 测试姿态分析
    print("\n4. 测试姿态分析...")
    try:
        # 获取朝向和关键点索引
        facing_direction = find_camera_facing_side(all_keypoints[0])
        front_indices = get_front_keypoint_indices(facing_direction)
        print(f"  - 检测到的朝向: {facing_direction}")
        print(f"  - 关键点索引: {front_indices}")
        
        # 测试膝盖角度计算
        print("\n  测试膝盖角度计算:")
        # 获取一些示例帧的膝盖角度
        hip_knee_ankle_indices = front_indices[:4]
        sample_angles = [get_hip_knee_ankle_angle(kp, hip_knee_ankle_indices) for kp in all_keypoints[:5]]
        print(f"  - 前5帧的膝盖角度: {[f'{angle:.2f}°' for angle in sample_angles]}")
        
        # 测试最低点检测
        lowest_indices = get_lowest_pedal_frames(all_keypoints, hip_knee_ankle_indices)
        print(f"  - 检测到的最低点帧索引: {lowest_indices[:5]}")
        
        # 测试最高点检测
        highest_indices = get_highest_pedal_frames(all_keypoints, hip_knee_ankle_indices)
        print(f"  - 检测到的最高点帧索引: {highest_indices[:5]}")
        
        # 获取完整结果
        result = get_pose(all_keypoints)
        print("\n姿态分析结果:")
        print(f"  - 最低点膝盖角度: {result['knee_angle_lowest']:.2f}°")
        print(f"  - 最高点膝盖角度: {result['knee_angle_highest']:.2f}°")
        print(f"  - 肩膀角度: {result['shoulder_angle']:.2f}°")
        print(f"  - 手肘角度: {result['elbow_angle']:.2f}°")
        print(f"  - 髋关节角度: {result['hip_angle']:.2f}°")
        print("✓ 姿态分析成功")
    except Exception as e:
        print(f"✗ 姿态分析失败: {str(e)}")
        import traceback
        print(traceback.format_exc())

if __name__ == "__main__":
    test_pose_analyzer()
