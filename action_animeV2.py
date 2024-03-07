import time
import random
import math
from collections import deque

# mouth_eye_vector_c:
# 2, 3是右眼和左眼开闭（0-1）*******
# 12, 13是右眼和左眼球大小（1为极小）
# 14是高兴嘴巴aaa （1完全张开，负数似乎会变成^）*******
# 15是嘴巴iii
# 16是嘴巴uuu
# 17是嘴巴eee
# 18是惊讶嘴巴ooo（能拉到10）
# 19是三角嘴巴delta
# 21豆豆嘴（能拉到10）
# 25眼球上下（-1到1，-1向下）*******
# 26眼球左右（-1到1，-1向右）*******

# pose_vector_c:
# 0是抬头低头（-1到1，-1低头）*******
# 1是左右转头（-1到1，-1向右）*******
# 2是左右侧头（-1到1，-1向右）*******

# eyebrow_vector_c:
# 0, 1皱眉（0-1， 0为右眉）
# 2, 3生气眉（0-1， 2为右眉）
# 4, 5眉毛降低（0-1， 4为右眉）
# 6, 7眉毛升高（0-1， 6为右眉）


HALF_PI = math.pi / 2
ActionState = {
    'idle': 0,
    'speak': 1,
    'rhythm': 2,
    'sleep': 3,
    'singing': 4
}


def calc_cur(start, end, period):
    return start + math.sin(period) * (end - start)


class ActionAnimeV2:
    def __init__(self):
        self.action_state = [False] * len(ActionState)  # 同时只能有1个为True，用作动作状态过渡

        self.eyebrow_vector_c = [0.0] * 12
        self.mouth_eye_vector_c = [0.0] * 27
        self.pose_vector_c = [0.0] * 6

        self.eyelid = deque()  # [[lstart, lend], [rstart, rend], [start_time, end_time]]
        self.eyeball = deque()  # [[xstart, xend], [ystart, yend], [start_time, end_time]]
        self.mouth = deque()  # [[start, end], [start_time, end_time], type]
        self.head_axial = deque()  # [[start, end], [start_time, end_time]]
        self.head_coronal = deque()  # [[start, end], [start_time, end_time]]
        self.head_sagittal = deque()  # [[start, end], [start_time, end_time]]

    def singing(self, beat_q, mouth_q):
        if beat_q is None or mouth_q is None:
            return self.calc_cur_vector()
        state_idx = ActionState['singing']
        if not self.action_state[state_idx]:
            self.action_state = [False] * len(ActionState)
            self.action_state[state_idx] = True
            self.reset_deque()
            self.check_deque()  # 所有回正

            # 根据节奏点头
            beat_times, beat_strengths = beat_q['beat_times'], beat_q['beat_strengths']
            for i, beat_time in enumerate(beat_times[1:]):
                s_cur, stength, beat_half = self.head_sagittal[-1][0][1], beat_strengths[i], (beat_time + beat_times[i]) / 2
                self.head_sagittal.append([[s_cur, 1.0 * stength], [beat_times[i], beat_half]])
                self.head_sagittal.append([[1.0 * stength, -0.8 * stength], [beat_half, beat_time]])

            # 嘴巴根据音量开合
            voice_times, voice_strengths = mouth_q['voice_times'], mouth_q['voice_strengths']
            for i, voice_time in enumerate(voice_times[1:]):
                m_cur = self.mouth[-1][0][1]
                self.mouth.append([[m_cur, voice_strengths[i]], [voice_times[i], voice_time], 14])

        if len(self.eyelid) <= 1 and random.uniform(0.0, 1.0) > 0.7:  # 随机闭眼
            l_cur, r_cur, t_cur = self.eyelid[-1][0][1], self.eyelid[-1][1][1], self.eyelid[-1][2][1]
            eyelid_end = random.choice([0.5, 1.0])  # 0.7
            self.eyelid.append([[l_cur, eyelid_end], [r_cur, eyelid_end], [t_cur, t_cur+0.8]])
            l_cur, r_cur, t_cur = self.eyelid[-1][0][1], self.eyelid[-1][1][1], self.eyelid[-1][2][1]
            self.eyelid.append([[l_cur, l_cur], [r_cur, r_cur], [t_cur, t_cur+random.uniform(2, 6)]])
            l_cur, r_cur, t_cur = self.eyelid[-1][0][1], self.eyelid[-1][1][1], self.eyelid[-1][2][1]
            self.eyelid.append([[l_cur, 0.3], [r_cur, 0.3], [t_cur, t_cur+0.8]])

        # 节奏没了继续摇，摇到歌曲播完为止（填补歌曲末尾的静默期）
        if len(self.head_sagittal) <= 1:
            beat_times, stength = beat_q['beat_times'], beat_q['beat_strengths'][-1]
            s_cur, beat_interval = self.head_sagittal[-1][0][1], beat_times[-1] - beat_times[-2]
            beat_start, beat_half = self.head_sagittal[-1][1][1], self.head_sagittal[-1][1][1] + beat_interval / 2
            self.head_sagittal.append([[s_cur, 1.0 * stength], [beat_start, beat_half]])
            self.head_sagittal.append([[1.0 * stength, -0.5 * stength], [beat_half, beat_start+beat_interval]])
        if len(self.head_coronal) <= 1:
            c_cur, t_cur = self.head_coronal[-1][0][1], self.head_coronal[-1][1][1]
            sign = 1 if c_cur == 0 else -c_cur / abs(c_cur)
            self.head_coronal.append([[c_cur, random.choice([0, 0.3, 0.6]) * sign], [t_cur, t_cur+0.6]])
            c_cur, t_cur = self.head_coronal[-1][0][1], self.head_coronal[-1][1][1]
            self.head_coronal.append([[c_cur, c_cur], [t_cur, t_cur+max(random.uniform(-0.5, 2.0), 0.0)]])
        self.auto_blink()
        self.eyeball_moving()
        return self.calc_cur_vector()

    def rhythm(self, beat_q):  # 根据节奏摇
        if beat_q is None:
            return self.calc_cur_vector()
        state_idx = ActionState['rhythm']
        if not self.action_state[state_idx]:
            self.action_state = [False] * len(ActionState)
            self.action_state[state_idx] = True
            self.reset_deque()
            self.check_deque()  # 所有回正

            beat_times, beat_strengths = beat_q['beat_times'], beat_q['beat_strengths']
            for i, beat_time in enumerate(beat_times[1:]):
                s_cur, stength, beat_half = self.head_sagittal[-1][0][1], beat_strengths[i], (beat_time + beat_times[i]) / 2
                self.head_sagittal.append([[s_cur, 1.0 * stength], [beat_times[i], beat_half]])
                self.head_sagittal.append([[1.0 * stength, -0.5 * stength], [beat_half, beat_time]])

        if len(self.head_sagittal) <= 1:
            beat_times, stength = beat_q['beat_times'], beat_q['beat_strengths'][-1]
            s_cur, beat_interval = self.head_sagittal[-1][0][1], beat_times[-1] - beat_times[-2]
            beat_start, beat_half = self.head_sagittal[-1][1][1], self.head_sagittal[-1][1][1] + beat_interval / 2
            self.head_sagittal.append([[s_cur, 1.0 * stength], [beat_start, beat_half]])
            self.head_sagittal.append([[1.0 * stength, -0.5 * stength], [beat_half, beat_start+beat_interval]])
        if len(self.head_coronal) <= 1:
            c_cur, t_cur = self.head_coronal[-1][0][1], self.head_coronal[-1][1][1]
            sign = 1 if c_cur == 0 else -c_cur / abs(c_cur)
            self.head_coronal.append([[c_cur, random.choice([0, 0.3, 0.6]) * sign], [t_cur, t_cur+0.6]])
            c_cur, t_cur = self.head_coronal[-1][0][1], self.head_coronal[-1][1][1]
            self.head_coronal.append([[c_cur, c_cur], [t_cur, t_cur+random.uniform(0., 2.3)]])
        self.auto_blink()
        self.eyeball_moving()
        return self.calc_cur_vector()

    def speaking(self, speech_q):
        if speech_q is None:
            return self.calc_cur_vector()
        state_idx = ActionState['speak']
        if not self.action_state[state_idx]:
            self.action_state = [False] * len(ActionState)
            self.action_state[state_idx] = True
            self.reset_deque()
            self.check_deque()  # 所有回正

            # 嘴巴根据音量张合
            voice_times, voice_strengths = speech_q['voice_times'], speech_q['voice_strengths']
            for i, voice_time in enumerate(voice_times[1:]):
                m_cur = self.mouth[-1][0][1]
                self.mouth.append([[m_cur, voice_strengths[i]], [voice_times[i], voice_time], 14])

            # 眼睛随机半闭
            l_cur, r_cur, t_cur = self.eyelid[-1][0][1], self.eyelid[-1][1][1], self.eyelid[-1][2][1]
            eyelid_end = random.choice([0., 0.3, 0.6])
            self.eyelid.append([[l_cur, eyelid_end], [r_cur, eyelid_end], [t_cur, t_cur+0.5]])

        if len(self.head_coronal) <= 1:
            c_cur, t_cur = self.head_coronal[-1][0][1], self.head_coronal[-1][1][1]
            self.head_coronal.append([[c_cur, random.choice([-0.4, -0.2, 0, 0.2, 0.4])], [t_cur, t_cur+0.5]])
            c_cur, t_cur = self.head_coronal[-1][0][1], self.head_coronal[-1][1][1]
            self.head_coronal.append([[c_cur, c_cur], [t_cur, t_cur+random.uniform(0., 1.)]])
        if len(self.head_axial) <= 1:
            a_cur, t_cur = self.head_axial[-1][0][1], self.head_axial[-1][1][1]
            self.head_axial.append([[a_cur, random.uniform(-0.3, 0.6)], [t_cur, t_cur + random.uniform(0.2, 1.5)]])
            a_cur, t_cur = self.head_axial[-1][0][1], self.head_axial[-1][1][1]
            self.head_axial.append([[a_cur, a_cur], [t_cur, t_cur+max(random.uniform(-0.5, 1.5), 0)]])
        self.auto_blink()
        self.eyeball_moving()
        return self.calc_cur_vector()

    def sleeping(self):
        state_idx = ActionState['sleep']
        if not self.action_state[state_idx]:
            self.action_state = [False] * len(ActionState)
            self.action_state[state_idx] = True
            self.reset_deque()
            self.check_deque()  # 所有回正

            enter_state_time, eye_close = 1.5, 0.85
            l_cur, r_cur, t_cur = self.eyelid[-1][0][1], self.eyelid[-1][1][1], self.eyelid[-1][2][1]
            self.eyelid.append([[l_cur, eye_close], [r_cur, eye_close], [t_cur, t_cur+enter_state_time]])
            c_cur, t_cur = self.head_coronal[-1][0][1], self.head_coronal[-1][1][1]
            self.head_coronal.append([[c_cur, random.choice([0.3, 0.6])], [t_cur, t_cur+enter_state_time]])
            m_cur, t_cur = self.mouth[-1][0][1], self.mouth[-1][1][1]
            self.mouth.append([[m_cur, 0.0], [t_cur, t_cur+enter_state_time], 14])
        if len(self.eyelid) <= 1:  # 保持闭眼
            l_cur, r_cur, t_cur = self.eyelid[-1][0][1], self.eyelid[-1][1][1], self.eyelid[-1][2][1]
            self.eyelid.append([[l_cur, l_cur], [r_cur, r_cur], [t_cur, t_cur + 1.]])
        if len(self.head_coronal) <= 1:  # 保持转头
            c_cur, t_cur = self.head_coronal[-1][0][1], self.head_coronal[-1][1][1]
            self.head_coronal.append([[c_cur, c_cur], [t_cur, t_cur + 1.]])
        # 模拟呼吸
        inhale_time, exhale_time = 0.8, 1.2  # 1.4, 2.0
        if len(self.head_sagittal) <= 1:
            s_cur, t_cur = self.head_sagittal[-1][0][1], self.head_sagittal[-1][1][1]
            self.head_sagittal.append([[s_cur, -0.2], [t_cur, t_cur+inhale_time]])
            s_cur, t_cur = self.head_sagittal[-1][0][1], self.head_sagittal[-1][1][1]
            self.head_sagittal.append([[s_cur, -0.4], [t_cur, t_cur+exhale_time]])
        if len(self.mouth) <= 1 and self.head_sagittal[-1][1][0] - self.mouth[-1][1][1] > 0.5:  # 嘴型过渡更平滑
            m_cur, t_cur = self.mouth[-1][0][1], self.mouth[-1][1][1]
            self.mouth.append([[m_cur, 0.8], [t_cur, self.head_sagittal[-1][1][0]], 14])
            m_cur, t_cur = self.mouth[-1][0][1], self.mouth[-1][1][1]
            self.mouth.append([[m_cur, 0.35], [self.head_sagittal[-1][1][0], self.head_sagittal[-1][1][1]], 14])
        return self.calc_cur_vector()

    def idle(self):
        state_idx = ActionState['idle']
        if not self.action_state[state_idx]:
            self.action_state = [False] * len(ActionState)
            self.action_state[state_idx] = True
            self.reset_deque()
            self.check_deque()  # 所有回正

        self.auto_blink(eyelid_random=True)
        self.eyeball_moving()
        self.head_moving()
        return self.calc_cur_vector()

    def auto_blink(self, eyelid_random=False):
        if len(self.eyelid) <= 1:
            for _ in range(4):  # 几率连续眨眼，最多n次
                eyelid = 1.0 if not eyelid_random else random.uniform(0.7, 1.2)
                self.blink(eyelid)
                if random.uniform(0., 1.) < 0.7:  # 几率连续眨眼
                    break
            l_cur, r_cur, t_cur = self.eyelid[-1][0][1], self.eyelid[-1][1][1], self.eyelid[-1][2][1]
            self.eyelid.append([[l_cur, l_cur], [r_cur, r_cur], [t_cur, t_cur+random.uniform(1.6, 3.1)]])

    def blink(self, eyelid):
        l_cur, r_cur = self.eyelid[-1][0][1], self.eyelid[-1][1][1]
        self.eyelid.append([[l_cur, eyelid], [r_cur, eyelid], [self.eyelid[-1][2][1], self.eyelid[-1][2][1] + 0.15]])
        self.eyelid.append([[eyelid, l_cur], [eyelid, r_cur], [self.eyelid[-1][2][1], self.eyelid[-1][2][1] + 0.15]])

    def eyeball_moving(self):
        if len(self.eyeball) <= 1:
            x_cur, y_cur, t_cur = self.eyeball[-1][0][1], self.eyeball[-1][1][1], self.eyeball[-1][2][1]
            self.eyeball.append([[x_cur, random.uniform(-0.3, 0.6)], [y_cur, random.uniform(-0.2, 0.4)],
                                 [t_cur, t_cur+random.uniform(0.2, 0.5)]])
            x_cur, y_cur, t_cur = self.eyeball[-1][0][1], self.eyeball[-1][1][1], self.eyeball[-1][2][1]
            self.eyeball.append([[x_cur, x_cur], [y_cur, y_cur], [t_cur, t_cur+random.uniform(0.2, 1.5)]])

    def head_moving(self):
        if len(self.head_axial) <= 1:
            a_cur, c_cur, s_cur = self.head_axial[-1][0][1], self.head_coronal[-1][0][1], self.head_sagittal[-1][0][1]
            t_cur, t_next = self.head_axial[-1][1][1], self.head_axial[-1][1][1] + random.uniform(0.5, 1.8)
            self.head_axial.append([[a_cur, random.uniform(-0.3, 0.6)], [t_cur, t_next]])
            self.head_coronal.append([[c_cur, random.uniform(-0.4, 0.4)], [t_cur, t_next]])
            self.head_sagittal.append([[s_cur, random.uniform(-0.2, 0.4)], [t_cur, t_next]])
            a_cur, c_cur, s_cur = self.head_axial[-1][0][1], self.head_coronal[-1][0][1], self.head_sagittal[-1][0][1]
            t_cur, t_next = self.head_axial[-1][1][1], self.head_axial[-1][1][1] + max(random.uniform(-0.5, 1.5), 0)
            self.head_axial.append([[a_cur, a_cur], [t_cur, t_next]])
            self.head_coronal.append([[c_cur, c_cur], [t_cur, t_next]])
            self.head_sagittal.append([[s_cur, s_cur], [t_cur, t_next]])

    def calc_cur_vector(self):
        eyebrow_vector_c = [0.0] * 12
        mouth_eye_vector_c = [0.0] * 27
        pose_vector_c = [0.0] * 6

        self.deque_pop_outdated()
        self.check_deque()
        cur_time = time.perf_counter()

        period = (cur_time - self.eyelid[0][2][0]) / (self.eyelid[0][2][1] - self.eyelid[0][2][0]) * HALF_PI
        mouth_eye_vector_c[3] = calc_cur(self.eyelid[0][0][0], self.eyelid[0][0][1], period)
        mouth_eye_vector_c[2] = calc_cur(self.eyelid[0][1][0], self.eyelid[0][1][1], period)

        period = (cur_time - self.eyeball[0][2][0]) / (self.eyeball[0][2][1] - self.eyeball[0][2][0]) * HALF_PI
        mouth_eye_vector_c[26] = calc_cur(self.eyeball[0][0][0], self.eyeball[0][0][1], period)
        mouth_eye_vector_c[25] = calc_cur(self.eyeball[0][1][0], self.eyeball[0][1][1], period)

        period = (cur_time - self.mouth[0][1][0]) / (self.mouth[0][1][1] - self.mouth[0][1][0]) * HALF_PI
        mouth_eye_vector_c[self.mouth[0][2]] = calc_cur(self.mouth[0][0][0], self.mouth[0][0][1], period)

        period = (cur_time - self.head_axial[0][1][0]) / (self.head_axial[0][1][1] - self.head_axial[0][1][0]) * HALF_PI
        pose_vector_c[1] = calc_cur(self.head_axial[0][0][0], self.head_axial[0][0][1], period)

        period = (cur_time - self.head_coronal[0][1][0]) / (self.head_coronal[0][1][1] - self.head_coronal[0][1][0]) * HALF_PI
        pose_vector_c[2] = calc_cur(self.head_coronal[0][0][0], self.head_coronal[0][0][1], period)

        period = (cur_time - self.head_sagittal[0][1][0]) / (self.head_sagittal[0][1][1] - self.head_sagittal[0][1][0]) * HALF_PI
        pose_vector_c[0] = calc_cur(self.head_sagittal[0][0][0], self.head_sagittal[0][0][1], period)

        self.eyebrow_vector_c = eyebrow_vector_c
        self.mouth_eye_vector_c = mouth_eye_vector_c
        self.pose_vector_c = pose_vector_c
        return eyebrow_vector_c, mouth_eye_vector_c, pose_vector_c

    def check_deque(self):
        # 检查depue是否为空，若为空则加入归正动作
        cur_time = time.perf_counter()
        return_time = cur_time + 0.3  # 回正时长
        if len(self.eyelid) == 0:
            self.eyelid.append([[self.mouth_eye_vector_c[3], 0], [self.mouth_eye_vector_c[2], 0], [cur_time, return_time]])
        if len(self.eyeball) == 0:
            self.eyeball.append([[self.mouth_eye_vector_c[26], 0], [self.mouth_eye_vector_c[25], 0], [cur_time, return_time]])
        if len(self.mouth) == 0:
            mouth_type = 14
            for i in range(mouth_type, mouth_type + 4 + 1):
                if self.mouth_eye_vector_c[i] > 0.:
                    mouth_type = i
                    break
            self.mouth.append([[self.mouth_eye_vector_c[mouth_type], 0], [cur_time, cur_time + 0.05], mouth_type])
        if len(self.head_axial) == 0:
            self.head_axial.append([[self.pose_vector_c[1], 0], [cur_time, return_time]])
        if len(self.head_coronal) == 0:
            self.head_coronal.append([[self.pose_vector_c[2], 0], [cur_time, return_time]])
        if len(self.head_sagittal) == 0:
            self.head_sagittal.append([[self.pose_vector_c[0], 0], [cur_time, return_time]])

    def deque_pop_outdated(self):
        cur_time = time.perf_counter()
        while len(self.eyelid) > 0:
            if self.eyelid[0][2][1] < cur_time:
                self.eyelid.popleft()
            else:
                break
        cur_time = time.perf_counter()
        while len(self.eyeball) > 0:
            if self.eyeball[0][2][1] < cur_time:
                self.eyeball.popleft()
            else:
                break
        cur_time = time.perf_counter()
        while len(self.mouth) > 0:
            if self.mouth[0][1][1] < cur_time:
                self.mouth.popleft()
            else:
                break
        cur_time = time.perf_counter()
        while len(self.head_axial) > 0:
            if self.head_axial[0][1][1] < cur_time:
                self.head_axial.popleft()
            else:
                break
        cur_time = time.perf_counter()
        while len(self.head_coronal) > 0:
            if self.head_coronal[0][1][1] < cur_time:
                self.head_coronal.popleft()
            else:
                break
        cur_time = time.perf_counter()
        while len(self.head_sagittal) > 0:
            if self.head_sagittal[0][1][1] < cur_time:
                self.head_sagittal.popleft()
            else:
                break

    def reset_deque(self):
        self.eyelid = deque()
        self.eyeball = deque()
        self.mouth = deque()
        self.head_axial = deque()
        self.head_coronal = deque()
        self.head_sagittal = deque()





