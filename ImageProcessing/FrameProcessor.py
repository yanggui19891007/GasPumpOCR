import cv2
import numpy as np
import os
from ImageProcessing.OpenCVUtils import inverse_colors, sort_contours

RESIZED_IMAGE_WIDTH = 20
RESIZED_IMAGE_HEIGHT = 30
CROP_DIR = 'crops'


class FrameProcessor:
    def __init__(self, height, version, debug=False, write_digits=False):
        self.debug = debug
        self.version = version
        self.height = height
        self.file_name = None
        self.img = None
        self.width = 0
        self.original = None
        self.write_digits = write_digits

        self.knn = self.train_knn(self.version)

    def set_image(self, file_name):
        self.file_name = file_name
        self.img = cv2.imread(file_name)
        self.original, self.width = self.resize_to_height(self.height)
        self.img = self.original.copy()

    def resize_to_height(self, height):
        r = self.img.shape[0] / float(height)
        dim = (int(self.img.shape[1] / r), height)
        img = cv2.resize(self.img, dim, interpolation=cv2.INTER_AREA)
        return img, dim[0]

    def train_knn(self, version):
        npa_classifications = np.loadtxt("knn/classifications" + version + ".txt",
                                         np.float32)  # read in training classifications
        npa_flattened_images = np.loadtxt("knn/flattened_images" + version + ".txt",
                                          np.float32)  # read in training images

        npa_classifications = npa_classifications.reshape(
            (npa_classifications.size, 1))  # reshape numpy array to 1d, necessary to pass to call to train
        k_nearest = cv2.ml.KNearest_create()  # instantiate KNN object
        k_nearest.train(npa_flattened_images, cv2.ml.ROW_SAMPLE, npa_classifications)
        return k_nearest

    def process_image(self, blur, threshold, adjustment, erode, iterations):
        # erode = 2
        # thresh = 71
        # adjustment = 15
        # iterations = 4
        # blur = 9

        self.img = self.original.copy()

        debug_images = []

        alpha = float(2.5)
        beta = float(0)

        exposure_img = cv2.multiply(self.img, np.array([alpha]))
        debug_images.append(('Exposure Adjust', exposure_img))

        brite_img = cv2.add(exposure_img, np.array([beta]))
        debug_images.append(('Briteness Adjust', brite_img))

        # Convert to grayscale
        img2gray = cv2.cvtColor(self.img, cv2.COLOR_BGR2GRAY)
        debug_images.append(('Grayscale', img2gray))

        # Blur to reduce noise
        img_blurred = cv2.GaussianBlur(img2gray, (blur, blur), 0)
        debug_images.append(('Blurred', img_blurred))

        # Crop image to LCD Panel section or at least try to
        # cropped, panel_bounds, additional_debug_images = find_panel(img_blurred)
        # debug_images += additional_debug_images

        cropped = img_blurred

        cropped_threshold = cv2.adaptiveThreshold(cropped, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY,
                                                  threshold, adjustment)
        debug_images.append(('Cropped Threshold', cropped_threshold))

        # Dilate the lcd digits to make them continuous for easier contouring
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (erode, erode))
        dilated = cv2.erode(cropped_threshold, kernel, iterations=iterations)
        debug_images.append(('Dilated', dilated))

        # Reverse the image to so the white text is found when looking for the contours
        inverse = inverse_colors(dilated)
        debug_images.append(('Inversed', inverse))

        # Find the lcd digit contours
        _, contours, _ = cv2.findContours(inverse, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)  # get contours

        # Assuming we find some, we'll sort them in order left -> right
        if len(contours) > 0:
            contours, _ = sort_contours(contours)

        potential_decimals = []
        potential_digits = []

        total_digit_height = 0
        total_digit_y = 0

        desired_aspect = 0.6
        digit_one_aspect = 0.3
        aspect_buffer = 0.15

        for contour in contours:
            # get rectangle bounding contour
            [x, y, w, h] = cv2.boundingRect(contour)

            aspect = float(w) / h
            size = w * h

            # It's a square
            if size > 100 and aspect >= 1 - .3 and aspect <= 1 + .3:
                potential_decimals.append(contour)

            # If it's small and it's not a  square, kick it out
            if size < 20 * 100 and (aspect < 1 - aspect_buffer and aspect > 1 + aspect_buffer):
                continue

            # Ignore any rectangles where the width is greater than the height
            if w > h:
                if self.debug:
                    cv2.rectangle(self.img, (x, y), (x + w, y + h), (0, 0, 255), 2)
                continue

            if ((
                                    size > 2000 and aspect >= desired_aspect - aspect_buffer and aspect <= desired_aspect + aspect_buffer) or
                    (
                                        size > 1000 and aspect >= digit_one_aspect - aspect_buffer and aspect <= digit_one_aspect + aspect_buffer)):
                total_digit_height += h
                total_digit_y += y
                potential_digits.append(contour)
            else:
                if self.debug:
                    cv2.rectangle(self.img, (x, y), (x + w, y + h), (0, 0, 255), 2)

        avg_digit_height = 0
        avg_digit_y = 0
        potential_digits_count = len(potential_digits)
        left_most_digit = 0
        right_most_digit = 0
        digit_x_positions = []

        if potential_digits_count > 0:
            avg_digit_height = float(total_digit_height) / potential_digits_count
            avg_digit_y = float(total_digit_y) / potential_digits_count
            if self.debug:
                print "Average Digit Height and Y: " + str(avg_digit_height) + " and " + str(avg_digit_y)

        output = ''
        ix = 0
        for pot_digit in potential_digits:
            [x, y, w, h] = cv2.boundingRect(pot_digit)

            if h <= avg_digit_height * 1.2 and h >= avg_digit_height * 0.2 and y <= avg_digit_height * 1.2 and y >= avg_digit_y * 0.2:
                # Draw match
                cropped = dilated[y:y + h, x: x + w]
                cv2.rectangle(self.img, (x, y), (x + w, y + h), (255, 0, 0), 2)
                debug_images.append(('digit' + str(ix), cropped))

                digit = self.predict_digit(cropped)
                if self.debug:
                    print "Digit: " + digit
                output += digit

                if self.write_digits:
                    _, full_file = os.path.split(self.file_name)
                    file_name = full_file.split('.')
                    crop_file_path = CROP_DIR + '/' + digit + '_' + file_name[0] + '_crop_' + str(ix) + '.png'
                    cv2.imwrite(crop_file_path, cropped)

                if left_most_digit == 0 or x < left_most_digit:
                    left_most_digit = x

                if right_most_digit == 0 or x > right_most_digit:
                    right_most_digit = x + w

                digit_x_positions.append(x)

                ix += 1
            else:
                if self.debug:
                    cv2.rectangle(self.img, (x, y), (x + w, y + h), (66, 146, 244), 2)

        decimal_x = 0
        for pot_decimal in potential_decimals:
            [x, y, w, h] = cv2.boundingRect(pot_decimal)

            if x < right_most_digit and x > left_most_digit and y > (self.height / 2):
                cv2.rectangle(self.img, (x, y), (x + w, y + h), (255, 0, 0), 2)
                decimal_x = x

        for ix, digit_x in enumerate(digit_x_positions):
            if digit_x > decimal_x:
                # insert
                output = output[:ix] + '.' + output[ix:]
                break

        if self.debug:
            cv2.rectangle(self.img, (left_most_digit, int(avg_digit_y)),
                          (left_most_digit + right_most_digit - left_most_digit,
                           int(avg_digit_y) + int(avg_digit_height)),
                          (66, 244, 212), 2)

        if self.debug:
            print "Potential Digits " + str(len(potential_digits))
            print "Potential Decimals " + str(len(potential_decimals))
            print "String: " + output

        return debug_images, output

    def predict_digit(self, digit_mat):
        imgROIResized = cv2.resize(digit_mat, (RESIZED_IMAGE_WIDTH, RESIZED_IMAGE_HEIGHT))
        npaROIResized = imgROIResized.reshape((1, RESIZED_IMAGE_WIDTH * RESIZED_IMAGE_HEIGHT))
        npaROIResized = np.float32(npaROIResized)
        _, results, neigh_resp, dists = self.knn.findNearest(npaROIResized, k=1)
        predicted_digit = str(chr(int(results[0][0])))
        if predicted_digit == 'A':
            predicted_digit = '.'
        return predicted_digit
