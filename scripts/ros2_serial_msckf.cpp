/*
 * NavCore: deterministic serial runner for OpenVINS on ROS 2 bags.
 *
 * Reads a rosbag2 directly, in recorded order, and hands each message to the same ROS2Visualizer callbacks that the
 * live subscriber uses, with use_multi_threading_subs = false so that every camera frame is processed in order inside
 * the IMU callback. No real-time playback is involved, so a run gives the same result every time (OpenVINS ships a
 * runner like this for ROS 1 only).
 *
 * Usage: ros2 run ov_msckf ros2_serial_msckf <estimator_config.yaml> --ros-args -p path_bag:=<bag folder> [other -p ...]
 *
 * Monte Carlo runs on one sequence: -p navcore_dither_seed:=<n> (n > 0) adds seeded zero-mean Gaussian noise to every IMU
 * sample, with standard deviation navcore_dither_frac (default 0.1) times the configured discrete IMU noise
 * (density x sqrt(200 Hz)). Each seed is exactly repeatable; different seeds give different realisations, so methods
 * can be compared paired by seed, as in simulation. Seed 0 or unset: no dither.
 *
 * -p navcore_bag_start:=<seconds> skips the start of the bag (OpenVINS's own EuRoC script skips the hand-carried start of
 * the machine hall sequences: MH_04 10 s, MH_05 5 s). Default 0.
 */

#include <cstdlib>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <memory>
#include <random>
#include <string>
#include <vector>

#include <rclcpp/rclcpp.hpp>
#include <rclcpp/serialization.hpp>
#include <rclcpp/serialized_message.hpp>
#include <rosbag2_cpp/reader.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <sensor_msgs/msg/imu.hpp>

#include "core/VioManager.h"
#include "core/VioManagerOptions.h"
#include "ros/ROS2Visualizer.h"
#include "utils/colors.h"
#include "utils/opencv_yaml_parse.h"
#include "utils/print.h"

using namespace ov_msckf;

std::shared_ptr<VioManager> sys;
std::shared_ptr<ROS2Visualizer> viz;

int main(int argc, char **argv) {

  // Configuration path, as for the live subscriber
  std::string config_path = "unset_path_to_config.yaml";
  if (argc > 1) {
    config_path = argv[1];
  }

  rclcpp::init(argc, argv);
  rclcpp::NodeOptions options;
  options.allow_undeclared_parameters(true);
  options.automatically_declare_parameters_from_overrides(true);
  auto node = std::make_shared<rclcpp::Node>("ros2_serial_msckf", options);
  node->get_parameter<std::string>("config_path", config_path);

  auto parser = std::make_shared<ov_core::YamlParser>(config_path);
  parser->set_node(node);
  std::string verbosity = "INFO";
  parser->parse_config("verbosity", verbosity);
  ov_core::Printer::setPrintLevel(verbosity);

  VioManagerOptions params;
  params.print_and_load(parser);
  params.use_multi_threading_subs = false; // process every frame in order, inside the IMU callback
  sys = std::make_shared<VioManager>(params);
  viz = std::make_shared<ROS2Visualizer>(node, sys);

  // Topics from the calibration files, exactly as the live subscriber reads them
  std::string topic_imu = "/imu0";
  parser->parse_external("relative_config_imu", "imu0", "rostopic", topic_imu);
  std::vector<std::string> topic_cams;
  for (int i = 0; i < params.state_options.num_cameras; i++) {
    std::string topic = "/cam" + std::to_string(i) + "/image_raw";
    parser->parse_external("relative_config_imucam", "cam" + std::to_string(i), "rostopic", topic);
    topic_cams.push_back(topic);
  }
  if (!parser->successful()) {
    PRINT_ERROR(RED "[SERIAL]: unable to parse all parameters, please fix\n" RESET);
    std::exit(EXIT_FAILURE);
  }
  if (params.state_options.num_cameras != 2 || !params.use_stereo) {
    PRINT_ERROR(RED "[SERIAL]: this runner handles a stereo pair only (max_cameras 2, use_stereo true)\n" RESET);
    std::exit(EXIT_FAILURE);
  }
  std::string path_bag;
  if (!node->get_parameter("path_bag", path_bag) || path_bag.empty()) {
    PRINT_ERROR(RED "[SERIAL]: pass the bag folder with -p path_bag:=<folder>\n" RESET);
    std::exit(EXIT_FAILURE);
  }

  // Seeded IMU dither for Monte Carlo runs (off unless navcore_dither_seed > 0)
  double bag_start = 0.0;
  node->get_parameter("navcore_bag_start", bag_start);
  int dither_seed = 0;
  double dither_frac = 0.1;
  node->get_parameter("navcore_dither_seed", dither_seed);
  node->get_parameter("navcore_dither_frac", dither_frac);
  const double sd_w = dither_frac * params.imu_noises.sigma_w * std::sqrt(200.0);
  const double sd_a = dither_frac * params.imu_noises.sigma_a * std::sqrt(200.0);
  std::mt19937 dither_gen(dither_seed > 0 ? (unsigned)dither_seed : 1u);
  std::normal_distribution<double> dither_n(0.0, 1.0);
  if (dither_seed > 0) {
    std::fprintf(stderr, "[NavCore] serial: IMU dither seed %d, gyro std %.3g rad/s, accel std %.3g m/s^2\n", dither_seed, sd_w, sd_a);
  }

  rosbag2_cpp::Reader reader;
  reader.open(path_bag);
  rclcpp::Serialization<sensor_msgs::msg::Imu> ser_imu;
  rclcpp::Serialization<sensor_msgs::msg::Image> ser_img;
  sensor_msgs::msg::Image::SharedPtr img0, img1;
  size_t n_imu = 0, n_pairs = 0, n_skipped = 0;
  int64_t t_first = -1;
  if (bag_start > 0.0) {
    std::fprintf(stderr, "[NavCore] serial: skipping the first %.2f s of the bag\n", bag_start);
  }

  while (rclcpp::ok() && reader.has_next()) {
    auto bag_msg = reader.read_next();
    if (t_first < 0) {
      t_first = bag_msg->time_stamp;
    }
    if ((double)(bag_msg->time_stamp - t_first) * 1e-9 < bag_start) {
      n_skipped++;
      continue;
    }
    rclcpp::SerializedMessage serialized(*bag_msg->serialized_data);
    if (bag_msg->topic_name == topic_imu) {
      auto msg = std::make_shared<sensor_msgs::msg::Imu>();
      ser_imu.deserialize_message(&serialized, msg.get());
      if (dither_seed > 0) {
        msg->angular_velocity.x += sd_w * dither_n(dither_gen);
        msg->angular_velocity.y += sd_w * dither_n(dither_gen);
        msg->angular_velocity.z += sd_w * dither_n(dither_gen);
        msg->linear_acceleration.x += sd_a * dither_n(dither_gen);
        msg->linear_acceleration.y += sd_a * dither_n(dither_gen);
        msg->linear_acceleration.z += sd_a * dither_n(dither_gen);
      }
      viz->callback_inertial(msg);
      n_imu++;
    } else if (bag_msg->topic_name == topic_cams.at(0)) {
      img0 = std::make_shared<sensor_msgs::msg::Image>();
      ser_img.deserialize_message(&serialized, img0.get());
    } else if (bag_msg->topic_name == topic_cams.at(1)) {
      img1 = std::make_shared<sensor_msgs::msg::Image>();
      ser_img.deserialize_message(&serialized, img1.get());
    }
    // A stereo pair: both images with the same stamp (EuRoC images are hardware-synchronised)
    if (img0 && img1 && img0->header.stamp.sec == img1->header.stamp.sec && img0->header.stamp.nanosec == img1->header.stamp.nanosec) {
      viz->callback_stereo(img0, img1, 0, 1);
      img0.reset();
      img1.reset();
      n_pairs++;
    }
  }

  std::fprintf(stderr, "[NavCore] serial: %zu IMU messages and %zu stereo pairs read from %s (%zu messages skipped at the start)\n", n_imu,
               n_pairs, path_bag.c_str(), n_skipped);
  viz->visualize_final();
  rclcpp::shutdown();
  return EXIT_SUCCESS;
}
