class LiveController < ApplicationController
  before_filter :authorize, :defaults
  before_filter :load_queue, :except => :status
  before_filter :load_status, :except => :update_order

  def status
    render :partial => "status", :locals => { :status => @status }
  end

  def update_order
    index = 0
    params[:nzb].each do |nzbId|
      if nzbId != @queue[index]["id"].to_s
        server.call('move', nzbId, index)
      end
      index += 1
    end
    @message = "Queue updated @ " + Time.now.to_s
  end

  def toggle_download
    if @status["is_paused"]
      server.call('continue')
    else
      server.call('pause')
    end
  end

end
