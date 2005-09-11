module LiveHelper
  def eta(seconds)
    hours = seconds / 60 / 60
    minutes = seconds / 60 % 60
    secs = seconds % 60
    "%02d:%02d:%02d" % [hours, minutes, secs]
  end
end
