#pragma once
#include <M5Unified.h>
#include <utility/imu/MPU6886_Class.hpp>
#include <esp_timer.h>
#include <math.h>

// MPU6886 hardware FIFO, owned exclusively by the UI's data job. The regular
// M5.Imu.update path is suspended while active; no second I2C/Lua thread.
// FIFO sample order/rate and actual host receipt times are distinct fields.
class FireDataImu {
 public:
  bool active() const {return active_;}
  uint8_t gyroFilter() const {return static_cast<uint8_t>((saved_[1]&0xF8)|1);}
  uint32_t accelRange() const {return accelRange_;}
  uint32_t gyroRange() const {return gyroRange_;}
  bool overflow() const {return overflow_;}
  bool begin(uint32_t rate) {
    if (active_ || (rate!=50 && rate!=100) || M5.Imu.getType()!=m5::imu_mpu6886) return false;
    device_=M5.Imu.getImuInstancePtr(0);if (!device_) return false;
    for (size_t i=0;i<sizeof(registers_);++i) if (!device_->readRegister(registers_[i],&saved_[i],1)) return false;
    if ((saved_[4]&0x40) || saved_[3]) return false;
    // Never set the M5 driver's private _fifo_en flag. We drain the FIFO
    // directly and restore every modified register at the exit boundary.
    active_=true;overflow_=false;
    const uint8_t gyro=static_cast<uint8_t>(saved_[0]&0xFC);
    const uint8_t config=static_cast<uint8_t>((saved_[1]&0xF8)|1);
    const auto set=[&](uint8_t reg,uint8_t value) {
      uint8_t actual=0;
      return device_->writeRegister8(reg,value) && device_->readRegister(reg,&actual,1) &&
          (reg==0x6A?(actual&~4u)==(value&~4u):actual==value);
    };
    if (!set(0x1B,gyro) || !set(0x1A,config) || !set(0x19,static_cast<uint8_t>(1000/rate-1)) ||
        !set(0x23,0xF8) || !set(0x6A,static_cast<uint8_t>(saved_[4]|0x44))) {
      end();return false;
    }
    uint8_t accel=0;
    if (!device_->readRegister(0x1C,&accel,1)) {end();return false;}
    accelRange_=2u<<((accel>>3)&3);gyroRange_=250u<<((gyro>>3)&3);
    accelScale_=static_cast<float>(accelRange_)/32768.0f;
    gyroScale_=static_cast<float>(gyroRange_)/32768.0f;
    return true;
  }
  bool end() {
    bool restored=true;
    if (active_ && device_) {
      device_->writeRegister8(0x23,0);device_->writeRegister8(0x6A,0x04);
      for (size_t i=0;i<sizeof(registers_);++i) {
        uint8_t actual=0;
        restored=device_->writeRegister8(registers_[i],saved_[i]) && device_->readRegister(registers_[i],&actual,1) && actual==saved_[i] && restored;
      }
    }
    active_=false;device_=nullptr;
    return restored;
  }
  // 1=fresh hardware packet, 0=FIFO empty, -1=I/O or overflow. No repeats.
  int sample(float* values,uint64_t& received) {
    if (!active_) return -1;
    uint8_t count[2],status=0,bytes[14];
    if (!device_->readRegister(0x3A,&status,1) || !device_->readRegister(0x72,count,2)) return -1;
    const uint16_t available=(static_cast<uint16_t>(count[0])<<8)|count[1];
    if ((status&0x10) || available>=1008) {overflow_=true;return -1;}
    if (available<sizeof(bytes)) return 0;
    if (!device_->readRegister(0x74,bytes,sizeof(bytes))) return -1;
    received=static_cast<uint64_t>(esp_timer_get_time());
    const uint8_t offsets[]={0,2,4,8,10,12};
    for (size_t i=0;i<6;++i) {
      const uint8_t at=offsets[i];
      const int16_t raw=static_cast<int16_t>((static_cast<uint16_t>(bytes[at])<<8)|bytes[at+1]);
      values[i]=raw*(i<3?accelScale_:gyroScale_);
      if (!isfinite(values[i])) return -1;
    }
    return 1;
  }
 private:
  m5::IMU_Base* device_=nullptr;
  bool active_=false;
  bool overflow_=false;
  const uint8_t registers_[5]={0x1B,0x1A,0x19,0x23,0x6A};
  uint8_t saved_[5]={};
  float accelScale_=0,gyroScale_=0;
  uint32_t accelRange_=0,gyroRange_=0;
};
