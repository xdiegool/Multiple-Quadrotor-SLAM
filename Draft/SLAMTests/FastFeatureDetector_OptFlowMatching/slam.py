#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import numpy as np
import glob
import cv2
import cv2_helpers as cvh
from cv2_helpers import rgb



def prepare_object_points(boardSize):
    """
    Prepare object points, like (0,0,0), (0,1,0), (0,2,0) ... ,(5,7,0).
    """
    objp = np.zeros((np.prod(boardSize), 3), np.float32)
    objp[:,:] = np.array([ map(float, [i, j, 0])
                            for i in range(boardSize[1])
                            for j in range(boardSize[0]) ])
    
    return objp


def load_camera_intrinsics(filename):
    from numpy import array
    cameraMatrix, distCoeffs, imageSize = \
            eval(open(filename, 'r').read())
    return cameraMatrix, distCoeffs, imageSize



def main():
    # Tweaking parameters
    max_OF_error = 12.
    max_radius_OF_to_FAST = {}
    max_dist_ratio = {}
    allow_chessboard_matcher_and_refiner = True
    
    # optimized for chessboard features
    max_radius_OF_to_FAST["chessboard"] = 4.    # FAST detects points *around* corners :(
    max_dist_ratio["chessboard"] = 1.    # disable ratio test
    
    # optimized for FAST features
    max_radius_OF_to_FAST["FAST"] = 2.
    max_dist_ratio["FAST"] = 0.7
    
    
    # Initially known data
    boardSize = (8, 6)
    objp = prepare_object_points(boardSize)
    
    cameraMatrix, distCoeffs, imageSize = \
            load_camera_intrinsics("camera_intrinsics.txt")
    
    
    # Initiate FAST object with default values
    fast = cv2.FastFeatureDetector()
    # Initiate BFMatcher object with default values
    matcher = cvh.BFMatcher()
    
    # Initiate 2d 3d arrays
    objectPoints = []
    imagePoints = []
    
    
    # Select working (or 'testing') set
    from glob import glob
    images = sorted(glob(os.path.join("captures", "*.jpeg")))
    
    left_img = cv2.imread(images[2])
    right_img = cv2.imread(images[3])
    
    
    # Detect left (key)points (TODO: make this general, part of the main loop)
    ret, left_points = cvh.extractChessboardFeatures(left_img, boardSize)
    if not ret:
        raise Exception("No chessboard features detected.")
    #left_keypoints = fast.detect(left_img)
    #left_points = np.array([kp.pt for kp in left_keypoints], dtype=np.float32)
    
    chessboard_idxs = set(range(len(left_points) / 2))
    triangl_idxs = set(range(len(left_points)))
    
    # Detect right (key)points
    right_keypoints = fast.detect(right_img)
    right_FAST_points = np.array([kp.pt for kp in right_keypoints], dtype=np.float32)
    
    # Visualize right_FAST_points
    print "Visualize right_FAST_points"
    cv2.imshow("img", cv2.drawKeypoints(
            right_img,
            [cv2.KeyPoint(p[0],p[1], 7.) for p in right_FAST_points],
            color=rgb(0,0,255) ))    # blue markers with size 7
    cv2.waitKey()
    
    # Calculate optical flow (= 'OF') field from left to right
    left_gray = cv2.cvtColor(left_img, cv2.COLOR_BGR2GRAY)
    right_gray = cv2.cvtColor(right_img, cv2.COLOR_BGR2GRAY)
    right_OF_points, status_OF, err_OF = cv2.calcOpticalFlowPyrLK(
            left_gray, right_gray,
            left_points )    # points to start from
    err_OF = err_OF.reshape(-1)
    
    def match_OF_based(right_OF_points, right_FAST_points,
                       err_OF, status_OF,
                       max_radius_OF_to_FAST, max_dist_ratio,
                       left_point_idxs = None):    # if not None, left_point_idxs specifies mask
        # Filter out the OF points with high error
        right_OF_points, right_OF_to_left_idxs = \
                zip(*[ (p, i) for i, p in enumerate(right_OF_points)
                                if status_OF[i] and    # only include correct OF-points
                                err_OF[i] < max_OF_error and    # error should be low enough
                                (left_point_idxs == None or i in left_point_idxs) ])    # apply mask
        right_OF_points = np.array(right_OF_points)
        
        # Visualize right_OF_points
        print "Visualize right_OF_points"
        cv2.imshow("img", cv2.drawKeypoints(
                right_img,
                [cv2.KeyPoint(p[0],p[1], 7.) for p in right_OF_points],
                color=rgb(0,0,255) ))    # blue markers with size 7
        cv2.waitKey()
        
        # Align right_OF_points with right_FAST_points by matching them
        matches_twoNN = matcher.radiusMatch(
                right_OF_points,    # query points
                right_FAST_points,    # train points
                max_radius_OF_to_FAST )
        
        # Filter out ambiguous matches by a ratio-test, and prevent duplicates
        best_dist_matches_by_trainIdx = {}    # duplicate prevention: trainIdx -> match_best_dist
        for query_matches in matches_twoNN:
            # Ratio test
            if not ( len(query_matches) == 1 or    # only one match, probably a good one
                    (len(query_matches) > 1 and    # if more than one, first two shouldn't lie too close
                    query_matches[0].distance / query_matches[1].distance < max_dist_ratio) ):
                continue
                
            # Relink match to use 'left_point' indices
            match = cv2.DMatch(
                    right_OF_to_left_idxs[query_matches[0].queryIdx],    # queryIdx: left_points
                    query_matches[0].trainIdx,    # trainIdx: right_FAST_points
                    query_matches[0].distance )
            
            # Duplicate prevention
            if (not match.trainIdx in best_dist_matches_by_trainIdx or    # no duplicate found
                    err_OF[match.queryIdx] <    # replace duplicate if inferior, based on err_OF
                        err_OF[best_dist_matches_by_trainIdx[match.trainIdx].queryIdx]):
                best_dist_matches_by_trainIdx[match.trainIdx] = match
        
        return best_dist_matches_by_trainIdx
    
    # Match between FAST -> FAST features
    matches_by_trainIdx = match_OF_based(
            right_OF_points, right_FAST_points, err_OF, status_OF,
            max_radius_OF_to_FAST["FAST"],
            max_dist_ratio["FAST"] )
    
    if allow_chessboard_matcher_and_refiner and chessboard_idxs:
        # Match between chessboard -> chessboard features
        matches_by_trainIdx_chessboard = match_OF_based(
                right_OF_points, right_FAST_points, err_OF, status_OF,
                max_radius_OF_to_FAST["chessboard"],
                max_dist_ratio["chessboard"],
                chessboard_idxs )    # set mask
        
        # Overwrite FAST -> FAST feature matches by chessboard -> chessboard feature matches
        matches_by_trainIdx.update(matches_by_trainIdx_chessboard)
        
        # Refine chessboard features
        chessboard_corners_idxs = list(matches_by_trainIdx_chessboard)
        chessboard_corners = right_FAST_points[chessboard_corners_idxs]
        cv2.cornerSubPix(
                right_gray, chessboard_corners,
                (11,11),    # window
                (-1,-1),    # deadzone
                (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001) )    # termination criteria
        right_FAST_points[chessboard_corners_idxs] = chessboard_corners
        
        # Update chessboard_idxs
        chessboard_idxs = set(matches_by_trainIdx_chessboard)
    
    
    # Partition matches to make a distinction between previously triangulated points and non-triangl.
    # memory preallocation
    matches_left_triangl_to_right_FAST = [None] * min(len(matches_by_trainIdx), len(triangl_idxs))
    matches_left_non_triangl_to_right_FAST = [None] * (len(matches_by_trainIdx) - len(triangl_idxs))
    i = j = 0
    for trainIdx in matches_by_trainIdx:
        match = matches_by_trainIdx[trainIdx]
        if matches_by_trainIdx[trainIdx].queryIdx in triangl_idxs:
            matches_left_triangl_to_right_FAST[i] = match
            i += 1
        else:
            matches_left_non_triangl_to_right_FAST[j] = match
            j += 1
    # and all matches together
    matches_left_to_right_FAST = matches_left_triangl_to_right_FAST + matches_left_non_triangl_to_right_FAST
    
    # Visualize (previously triangulated) left_points of corresponding outlier-filtered right_FAST_points
    print "Visualize (previously triangulated) left_points of corresponding outlier-filtered right_FAST_points"
    cv2.imshow("img", cv2.drawKeypoints(
            left_img,
            [cv2.KeyPoint(left_points[m.queryIdx][0],left_points[m.queryIdx][1], 7.) for m in matches_left_triangl_to_right_FAST],
            color=rgb(0,0,255) ))    # blue markers with size 7
    cv2.waitKey()
    
    # Visualize (previously triangulated) outlier-filtered right_FAST_points
    print "Visualize (previously triangulated) outlier-filtered right_FAST_points"
    cv2.imshow("img", cv2.drawKeypoints(
            right_img,
            [cv2.KeyPoint(right_FAST_points[m.trainIdx][0],right_FAST_points[m.trainIdx][1], 7.) for m in matches_left_triangl_to_right_FAST],
            color=rgb(0,0,255) ))    # blue markers with size 7
    cv2.waitKey()
    
    # Visualize (not yet triangulated) outlier-filtered right_FAST_points
    print "Visualize (not yet triangulated) outlier-filtered right_FAST_points"
    cv2.imshow("img", cv2.drawKeypoints(
            right_img,
            [cv2.KeyPoint(right_FAST_points[m.trainIdx][0],right_FAST_points[m.trainIdx][1], 7.) for m in matches_left_non_triangl_to_right_FAST],
            color=rgb(0,0,255) ))    # blue markers with size 7
    cv2.waitKey()


if __name__ == "__main__":
    main()