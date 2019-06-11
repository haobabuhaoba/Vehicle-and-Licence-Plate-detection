
import numpy as np
import matplotlib.pyplot as plt
import glob
from moviepy.editor import VideoFileClip
from collections import deque
from sklearn.utils.linear_assignment_ import linear_assignment

import helpers
import tracker as tr
import time
from kalman_yolo import Detector as YoloDetector
import cv2
import sys
from lpd_ import lpd


# Global variables to be used by funcitons of VideoFileClop
frame_count = 0  # frame counter

max_age = 20  # no.of consecutive unmatched detection before
# a track is deleted

min_hits = 1  # no. of consecutive matches needed to establish a track

tracker_list = []  # list for trackers
# list for track ID
unq_ids = ['id' + str(i) for i in range(100)]
track_id_list = deque(unq_ids)
#track_id_list= deque(['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K','L','M','N','O'])


def assign_detections_to_trackers(trackers, detections, iou_thrd=0.3):
    '''
    From current list of trackers and new detections, output matched detections,
    unmatchted trackers, unmatched detections.
    '''

    IOU_mat = np.zeros((len(trackers), len(detections)), dtype=np.float32)
    for t, trk in enumerate(trackers):
        #trk = convert_to_cv2bbox(trk)
        for d, det in enumerate(detections):
         #   det = convert_to_cv2bbox(det)
            IOU_mat[t, d] = helpers.box_iou2(trk, det)

    # Produces matches
    # Solve the maximizing the sum of IOU assignment problem using the
    # Hungarian algorithm (also known as Munkres algorithm)

    matched_idx = linear_assignment(-IOU_mat)

    unmatched_trackers, unmatched_detections = [], []
    for t, trk in enumerate(trackers):
        if(t not in matched_idx[:, 0]):
            unmatched_trackers.append(t)

    for d, det in enumerate(detections):
        if(d not in matched_idx[:, 1]):
            unmatched_detections.append(d)

    matches = []

    # For creating trackers we consider any detection with an
    # overlap less than iou_thrd to signifiy the existence of
    # an untracked object

    for m in matched_idx:
        if(IOU_mat[m[0], m[1]] < iou_thrd):
            unmatched_trackers.append(m[0])
            unmatched_detections.append(m[1])
        else:
            matches.append(m.reshape(1, 2))

    if(len(matches) == 0):
        matches = np.empty((0, 2), dtype=int)
    else:
        matches = np.concatenate(matches, axis=0)

    return matches, np.array(unmatched_detections), np.array(unmatched_trackers)


def pipeline(img,lpd):
    '''
    Pipeline function for detection and tracking
    '''
    global frame_count
    global tracker_list
    global max_age
    global min_hits
    global track_id_list
    global debug

    frame_count += 1
    print("")
    print(frame_count)
    print("")
    start = time.time()
    img_dim = (img.shape[1], img.shape[0])

    # YOLO detection for vehicle
    yolo_start = time.time()
    z_box = yolo_det.get_detected_boxes(img)
    z_box_cpy= z_box
    yolo_end = time.time()

    # Lpd
    
    print("Time taken for yolo detection is", yolo_end-yolo_start)
    track_start = time.time()
    if debug:
        print('Frame:', frame_count)

    x_box = []
    if debug:
        for i in range(len(z_box)):
            img1 = helpers.draw_box_label(img, z_box[i], box_color=(255, 0, 0))
            cv2.imshow("frame", img1)
            k = cv2.waitKey(10)
            if k == ord('e'):
                cv2.destroyAllWindows()
                sys.exit(-1)

        # plt.show()

    if len(tracker_list) > 0:
        for trk in tracker_list:
            x_box.append(trk.box)

    matched, unmatched_dets, unmatched_trks \
        = assign_detections_to_trackers(x_box, z_box, iou_thrd=0.3)
    if debug:
        print('Detection: ', z_box)
        print('x_box: ', x_box)
        print('matched:', matched)
        print('unmatched_det:', unmatched_dets)
        print('unmatched_trks:', unmatched_trks)

    # Deal with matched detections
    if matched.size > 0:
        for trk_idx, det_idx in matched:
            z = z_box[det_idx]
            z = np.expand_dims(z, axis=0).T
            tmp_trk = tracker_list[trk_idx]
            tmp_trk.kalman_filter(z)
            xx = tmp_trk.x_state.T[0].tolist()
            xx = [xx[0], xx[2], xx[4], xx[6]]
            x_box[trk_idx] = xx
            tmp_trk.box = xx
            tmp_trk.hits += 1
            tmp_trk.no_losses = 0

    # Deal with unmatched detections
    if len(unmatched_dets) > 0:
        for idx in unmatched_dets:
            z = z_box[idx]
            z = np.expand_dims(z, axis=0).T
            tmp_trk = tr.Tracker()  # Create a new tracker
            x = np.array([[z[0], 0, z[1], 0, z[2], 0, z[3], 0]]).T
            tmp_trk.x_state = x
            tmp_trk.predict_only()
            xx = tmp_trk.x_state
            xx = xx.T[0].tolist()
            xx = [xx[0], xx[2], xx[4], xx[6]]
            tmp_trk.box = xx
            tmp_trk.id = track_id_list.popleft()  # assign an ID for the tracker
            tracker_list.append(tmp_trk)
            x_box.append(xx)

    # Deal with unmatched tracks
    if len(unmatched_trks) > 0:
        for trk_idx in unmatched_trks:
            tmp_trk = tracker_list[trk_idx]
            tmp_trk.no_losses += 1
            tmp_trk.predict_only()
            xx = tmp_trk.x_state
            xx = xx.T[0].tolist()
            xx = [xx[0], xx[2], xx[4], xx[6]]
            tmp_trk.box = xx
            x_box[trk_idx] = xx

    # The list of tracks to be annotated
    good_tracker_list = []
    for trk in tracker_list:
        if ((trk.hits >= min_hits) and (trk.no_losses <= max_age)):
            good_tracker_list.append(trk)
            x_cv2 = trk.box
            idx = trk.id
            if debug:
                print('updated box: ', x_cv2)
                print()
            # Draw the bounding boxes on the
            img = helpers.draw_box_label(img, x_cv2, idx)
    w, h = img_dim      
                                   # images
    dt_start = time.time()
    for i, box in enumerate(z_box_cpy):
        #Resolving the boxes for proper normalization
        y1_temp, x1_temp, y2_temp, x2_temp= box 
        w_temp= x2_temp-x1_temp
        h_temp= y2_temp- y1_temp

        plates = lpd.detectPlates(img, box, frame_count, i)
        for plate in plates:
            x1 = (plate[0][0]*w_temp +x1_temp).astype('int')
            y1 = (plate[1][0]*h_temp +y1_temp).astype('int')
            x2 = (plate[0][1]*w_temp +x1_temp).astype('int')
            y2 = (plate[1][1]*h_temp +y1_temp).astype('int')
            x3 = (plate[0][2]*w_temp +x1_temp).astype('int')
            y3 = (plate[1][2]*h_temp +y1_temp).astype('int')
            x4 = (plate[0][3]*w_temp +x1_temp).astype('int')
            y4 = (plate[1][3]*h_temp +y1_temp).astype('int')
            
            plate = np.array([[x1, y1], [x2, y2], [x3, y3], [x4, y4]], np.int32)
            plate = plate.reshape((-1, 1, 2))
            cv2.polylines(img, [plate], True, (0, 0, 255))
    dt_end = time.time()
    cv2.imwrite("output/finalImages/frame{}.png".format(frame_count),img )
    print("Time taken for plate detection is", dt_end - dt_start)
    dt_time = dt_end - dt_start
    
    track_end = time.time()
    print("Time taken to track the boxes is", track_end-track_start)
    end = time.time()
    fps = 1.0/(end-start)
    dt_fps = 1.0/(dt_time)
    cv2.putText(img, "FPS: {:.4f}".format(fps), (int(
        0.85*img_dim[0]), 200), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 4)
    cv2.putText(img, "Detect FPS: {:.4f}".format(
        dt_fps), (10, 200), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 4)
    # Book keeping
    deleted_tracks = filter(lambda x: x.no_losses > max_age, tracker_list)

    for trk in deleted_tracks:
        track_id_list.append(trk.id)

    tracker_list = [x for x in tracker_list if x.no_losses <= max_age]

    if debug:
        print('Ending tracker_list: ', len(tracker_list))
        print('Ending good tracker_list: ', len(good_tracker_list))

    return img


if __name__ == "__main__":

    #det = detector.CarDetector()

    debug = False
    interestedClass = ["car", "truck", "bus", "train"]
    yolo_det = YoloDetector(interestedClass)

    # test on a video file.
    input_file = sys.argv[1]
    output = input_file.split('.mp4')[0] + '_result_tracker.mp4'
    start = time.time()

    lpd = lpd("data/lp-detector/wpod-net_update1.h5")
    cap = cv2.VideoCapture(input_file)
    success = True
    while success:
        success, img = cap.read()
        if success:
            start_pipeline = time.time()
            img = pipeline(img, lpd)
            end_pipeline = time.time()
            print("Time taken for this iteration is",
                  round(end_pipeline-start_pipeline, 2))
            cv2.imshow("frame", img)
            cv2.waitKey(1)
    cap.release()
    # clip1 = VideoFileClip(input_file).subclip(14,19) # Set start and end time here
    # clip = clip1.fl_image(pipeline)
    # clip.write_videofile(output, audio=False)
    end = time.time()

    print(round(end-start, 2), 'Seconds to finish')
    #print(1000.0/(end-start), 'FPS')