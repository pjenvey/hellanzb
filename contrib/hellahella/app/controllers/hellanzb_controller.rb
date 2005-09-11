class HellanzbController < ApplicationController
  before_filter :authorize, :defaults
  before_filter :load_queue, :except => :index
  before_filter :load_status, :except => :queue
  
  def index
    @asciiart = server.call('asciiart')
  end
  
  def queue
  end
  
  def bandwidth
    if request.post?
      server.call('maxrate', params[:maxrate])
      session[:status] = nil
      load_status
    end
  end
end